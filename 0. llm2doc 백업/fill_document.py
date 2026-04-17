"""문서를 박스 단위로 순차 생성하는 초기 버전 실험 코드.

현재 메인 파이프라인은 `create_document.py` 계열이지만, 이 파일은
각 박스를 개별 LLM 호출로 채우는 방식이 어떻게 동작했는지 보여주는
이전 접근법의 흔적이다.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
from openai import OpenAI
from beartype import beartype

from .analyze_layout import LayoutAnalyzer
from .render_image import render_boxes, erase_bounding_box
from .util import image_as_data_uri


FILLABLE_BLOCKS = set(
    [
        "paragraph_title",
        "text",
        "doc_title",
        "paragraph_title",
        "vision_footnote",
        # "table",
        # "chart",
    ]
)


FILL_PROMPT = """
You are an automated document writer.

You will be given with:
- Reference document
  This is the desired *layout* of the document. Follow overall style and layout of this document.
- Target document
  This is the document you're currently writing.
- Desired content
  This is the *content* you need to write.

There will be striped bounding boxes in the document screenshots. To ensure they remain visible against any background color, these boxes are drawn with an alternating striped pattern (primary color, white, black, primary color). 
- Green-striped boxes represent areas you've already written.
- The blue-striped box represents what you need to write *right now*.
- Red-striped boxes represent areas you'll be writing *later*.

The boxes are drawn onto both the reference document and target document. Compare those two strategically to find out which content should go into the blue-striped box.

Your job is to read the desired content, and fill in the blue-striped box in the target document, keeping the style and layout of the reference document. This time, you only have to fill a single box. Keep in mind that you may need to split content into multiple boxes, especially if boxes are split over multiple paragraphs or pages.

Currently, the blue-striped box is at {blue_box_coords}, page_id={blue_box_page}.
If uncertain on where the box is, refer to the coordinates instead of guessing.
Coordinates is in format of [xmin, ymin, xmax, ymax] of 0-1000 relative scale.
Because box is at same position for both reference and target document, they are at the exact same coordinates.

**Output format**
You write a single code block containing desired content. For instance, if you want to fill the blue box with lorem ipsum, write:
```text
Lorem ipsum, dolar sit amet.
```

**Tips**
- The content you write will be filled into the blue box automatically.
- Make sure to write content worth of a single box, to be filled into the blue box.
- The renderer does not understand Markdown syntax. Anything you write will be treated as plain text. It is part of your job to translate Markdown to plain text, following style of reference document.
- Empty lines matter. The font size will be adjusted to fit the box. If you want some margin, Write few blank lines.
- Desired content contains the entire document worth of data. DO NOT attempt to fill all of it into a single box. You MUST find which content should go into the blue box.
- Everything that follows "[Desired content]" *is* the desired content. Don't be confused even if it contains some header-looking text!
- Even if you cannot visually locate the blue-striped box on the specified page_id, DO NOT look at other pages. You must blindly trust the provided coordinates to determine the location and size of the text you need to write.

Below is the input.
""".strip()


@beartype
def invoke_llm(
    client: OpenAI,
    index: int,
    target: list[Image.Image],
    rendered: list[Image.Image],
    desired_content: str,
    blue_box_coords: list[int],
    blue_box_page: int,
):
    """단일 박스를 채우기 위한 멀티모달 프롬프트를 만들고 LLM을 호출한다."""
    fill_prompt = FILL_PROMPT.format(
        blue_box_coords=blue_box_coords, blue_box_page=blue_box_page
    )

    content = [
        {
            "type": "input_text",
            "text": fill_prompt,
        },
    ]

    # 참고 문서 이미지는 "원래 어떤 스타일/배치였는지"를 알려주는 기준 역할을 한다.
    for i, img in enumerate(target):
        content.extend(
            [
                {
                    "type": "input_text",
                    "text": f"\n\n[Reference document, page_id={i + 1}]\n",
                },
                {
                    "type": "input_image",
                    "image_url": image_as_data_uri(img),
                },
            ]
        )

    # 현재 작성 중인 문서 스냅샷은 이미 채운 칸과 아직 비어 있는 칸을 보여준다.
    for i, img in enumerate(rendered):
        content.extend(
            [
                {
                    "type": "input_text",
                    "text": f"\n\n[Target document, page_id={i + 1}]\n",
                },
                {
                    "type": "input_image",
                    "image_url": image_as_data_uri(img),
                },
            ]
        )

    content.append(
        {
            "type": "input_text",
            "text": f"\n\n[Desired content]\n{desired_content}",
        }
    )

    response = client.responses.create(
        model=os.environ["OPENAI_MODEL"],
        input=[
            {
                "role": "user",
                "content": content,
            }
        ],
    )

    with open(f"debug_prompt_{index}.txt", "wt", encoding="utf-8") as f:
        f.write(fill_prompt)

    with open(f"debug_response_{index}.json", "wt", encoding="utf-8") as f:
        f.write(response.model_dump_json(indent=2))

    if any((x.type == "reasoning" for x in response.output)):
        with open(f"debug_reasoning_{index}.txt", "wt", encoding="utf-8") as f:
            for output in response.output:
                if output.type == "reasoning":
                    f.write(output.content[0].text)

    text = response.output_text
    text = text.strip()
    text = text.removeprefix("```text\n")
    text = text.removesuffix("\n```")
    return text


def fill_single_box(
    client: OpenAI,
    desired_content: str,
    page_blocks: list[list[list[int]]],
    images: list[Image.Image],
    erased_images: list[Image.Image],
    page: int,
    bbox_idx: int,
    index: int,
):
    """한 개의 bbox에 대해 입력 이미지를 준비하고 텍스트를 생성한다."""
    # 원본 이미지 위에 색상 박스를 덧그려 LLM이 레이아웃 기준을 파악하게 한다.
    target_imgs: list[Image.Image] = []
    for i, blk in enumerate(page_blocks):
        if page == i:
            selected = bbox_idx
        else:
            selected = -1

        img = images[page].copy()
        img = render_boxes(img, blk, selected=selected)
        target_imgs.append(img)

    # 배경만 남긴 이미지에도 동일한 박스를 그려 실제 작성 대상 위치를 보여준다.
    rendered_imgs: list[Image.Image] = []
    for i, blk in enumerate(page_blocks):
        if page == i:
            selected = bbox_idx
        else:
            selected = -1

        img = erased_images[i].copy()
        img = render_boxes(img, blk, selected=selected)
        rendered_imgs.append(img)

    target_imgs[page].save(f"debug_target_{index}.png")

    blue_box_coords = page_blocks[page][bbox_idx]

    # 좌표는 모델 프롬프트에서 0~1000 상대 좌표계로 전달한다.
    width = images[page].width
    height = images[page].height
    blue_box_coords = [
        blue_box_coords[0] * 1000 // width,
        blue_box_coords[1] * 1000 // height,
        blue_box_coords[2] * 1000 // width,
        blue_box_coords[3] * 1000 // height,
    ]

    text = invoke_llm(
        client,
        index,
        target_imgs,
        rendered_imgs,
        desired_content,
        blue_box_coords,
        page + 1,
    )

    return text


@beartype
def fill_document(
    client: OpenAI,
    desired_content: str,
    target_doc: str,
):
    """문서 전체의 fillable block을 병렬로 채워 보는 실험용 엔트리포인트."""
    print("[WARN] This code should not be used")

    layout_analyzer = LayoutAnalyzer()

    target_layout = layout_analyzer(target_doc)

    layout_analyzer.dispose()
    del layout_analyzer

    page_blocks = [
        [block.bbox for block in page.blocks if block.label in FILLABLE_BLOCKS]
        for page in target_layout.pages
    ]

    image_paths = [
        x for x in os.listdir(f"data/{target_doc}") if x.startswith("original")
    ]
    image_paths.sort()
    images = [Image.open(f"data/{target_doc}/{x}") for x in image_paths]

    # 먼저 기존 텍스트를 지운 빈 캔버스를 만들어, 생성 결과만 다시 올릴 준비를 한다.
    erased_images = []
    for blk, img in zip(page_blocks, images):
        img = img.copy()
        for bbox in blk:
            img = erase_bounding_box(img, bbox)
        erased_images.append(img)

    page_texts: list[list] = [[None for _ in page] for page in page_blocks]

    with ThreadPoolExecutor() as exe:
        cnt = 0

        for i, blocks in enumerate(page_blocks):
            for j, bbox in enumerate(blocks):
                page_texts[i][j] = exe.submit(
                    fill_single_box,
                    client,
                    desired_content,
                    page_blocks,
                    images,
                    erased_images,
                    i,
                    j,
                    cnt,
                )

                cnt += 1

        for i, blocks in enumerate(page_blocks):
            for j, bbox in enumerate(blocks):
                page_texts[i][j] = page_texts[i][j].result()

    for i, blk in enumerate(page_blocks):
        img = erased_images[i].copy()
        img = render_boxes(img, blk, page_texts[i], selected=None)
        img.save(f"debug_final_{i}.png")
