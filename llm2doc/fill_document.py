from io import BytesIO
import os
import json
import base64
from PIL import Image
from openai import OpenAI

from .render_image import render_boxes

prompt_preamble = """
You are an automated document writer.

You will be given with:
- Reference document
  This is the desired *layout* of the document. Follow overall shape and layout of this document.
- Target document
  This is the document you're currently writing.
- Desired content
  This is the content you need to write.

There will be boxes in the document screenshots. Green boxes represent ones you've already written. Blue box represent what you need to write *right now*. Red boxes represent ones you'll be writing *later*. Box is drawn onto both reference document and target document. So compare those two strategically to find out which content should go into the blue box.

Your job is to read desired content, and fill in the blue box in the target document, keeping style and layout of reference document. This time, you only have to fill a single box.

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

Below is the input.
""".strip()


def image_as_data_uri(img: Image.Image) -> str:
    buf = BytesIO()
    img.save(buf, "png")

    buf.seek(0)

    output = BytesIO(b"data:image/png;base64,")
    output.seek(0, 2)
    base64.encode(buf, output)

    return output.getvalue().decode()


def fill_single_box(
    client: OpenAI,
    index: int,
    template: Image.Image,
    rendered: Image.Image,
    desired_content: str,
):
    # Reference document with boxes
    image_a = image_as_data_uri(template)

    # The screenshot of document currently being written
    image_b = image_as_data_uri(rendered)

    response = client.responses.create(
        model=os.environ["OPENAI_MODEL"],
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt_preamble},
                    {
                        "type": "input_text",
                        "text": "\n\n[Reference document]",
                    },
                    {
                        "type": "input_image",
                        "image_url": image_a,
                    },
                    {"type": "input_text", "text": "\n\n[Target document]"},
                    {
                        "type": "input_image",
                        "image_url": image_b,
                    },
                    {
                        "type": "input_text",
                        "text": f"\n\n[Desired content]\n{desired_content}",
                    },
                ],
            }
        ],
    )

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


def fill_document():
    client = OpenAI(base_url=os.environ["OPENAI_BASE_URL"])

    with open("data/financial/bbox.json", "rb") as f:
        bboxes: list[list[float]] = json.load(f)

    with open("data/financial/target.txt", "rt", encoding="utf-8") as f:
        desired_content = f.read()

    texts: list[str | None] = [None for _ in bboxes]

    for curr_bbox_idx in range(len(bboxes)):
        img_template = Image.open("data/financial/original.png").convert("RGBA")
        img_template = render_boxes(img_template, bboxes, selected=curr_bbox_idx)

        img_rendered = Image.open("data/financial/erased.png").convert("RGBA")
        img_rendered = render_boxes(img_rendered, bboxes, texts, selected=curr_bbox_idx)

        text = fill_single_box(
            client, curr_bbox_idx, img_template, img_rendered, desired_content
        )
        texts[curr_bbox_idx] = text

    img_rendered = Image.open("data/financial/erased.png").convert("RGBA")
    img_rendered = render_boxes(img_rendered, bboxes, texts)
    img_template.save("data/financial/final.png")
