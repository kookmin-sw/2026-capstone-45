"""컨텍스트 강화 검색 도구를 사용하는 문서 생성 파이프라인의 변형 버전.

기본 구조는 `create_document.py`와 거의 같지만, 검색 단계에서
`ToolSearchSourceDocumentVer2`를 사용해 더 많은 주변 문맥을 모델에 제공한다.
"""

import json
import os
from copy import deepcopy
from typing import Sequence, cast

from bs4 import BeautifulSoup
from openai import OpenAI
from openai.types.responses.response_input_param import ResponseInputParam
from PIL import Image
from pydantic import BaseModel

from .analyze_layout import LayoutAnalyzer, ParsedDocument
from .create_document import PROMPT_WRITE, REGEX_DIV_ID
from .render_image import erase_bounding_box, render_boxes
from .tool_fetch_source_document import ToolFetchSourceDocument
from .tool_search_source_document_ver2 import ToolSearchSourceDocumentVer2


RESULT_OUTPUT_ROOT = r"C:\Users\echin\Desktop\ALLLM\llm-to-document\output"
RESULT_OUTPUT_DIR_NAME = "contextual_ver2"


def pydantic_encoder(obj):
    """Pydantic 객체를 디버그 저장용 일반 dict로 바꾼다."""
    if isinstance(obj, BaseModel):
        return obj.model_dump()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def write_document(
    client: OpenAI,
    query: str,
    src_docs: Sequence[ParsedDocument],
    target_doc: ParsedDocument,
    output_dir: str,
) -> str:
    """도구 호출 루프를 통해 최종 문서 응답을 생성한다."""
    imagine_prompt = PROMPT_WRITE.strip().format(
        query=query,
        target=target_doc.to_sturctured_html(doc_id="target"),
    )

    with open(os.path.join(output_dir, "debug_write_input.txt"), "wt", encoding="utf-8") as f:
        f.write(imagine_prompt)

    # 원문 검색은 ver2 검색기를 사용하고, 상세 페이지 조회는 동일하게 유지한다.
    tools = [
        ToolFetchSourceDocument(src_docs),
        ToolSearchSourceDocumentVer2([x.id for x in src_docs]),
    ]

    reasoning = cast(list[str], [])
    fulfilled_tool_calls: set[str] = set()
    final_output_retry_count = 0

    input_items: ResponseInputParam = [
        {
            "role": "user",
            "content": [{"type": "input_text", "text": imagine_prompt}],
        }
    ]

    while True:
        response = client.responses.create(
            model=os.environ["OPENAI_MODEL"],
            input=input_items,
            tools=[x.description for x in tools],
            tool_choice="auto",
        )

        for item in response.output:
            try:
                if item.type == "reasoning" and item.content is not None:
                    for content in item.content:
                        reasoning.append(content.text)
                elif item.type == "function_call" and item.arguments is not None:
                    reasoning.append(f"function_call={item.name} {item.arguments}")
            except Exception:
                pass

        input_items += response.output  # type: ignore

        tool_calls = [
            item
            for item in response.output
            if item.type == "function_call" and item.call_id not in fulfilled_tool_calls
        ]

        # 더 이상 도구 호출이 없으면 모델이 최종 출력을 시도한 상태로 본다.
        if not tool_calls:
            output_text = response.output_text.strip()
            if output_text == "" and final_output_retry_count < 2:
                final_output_retry_count += 1
                input_items.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": (
                                    "You have finished tool use. "
                                    "Now output only the final document as a single "
                                    '<document id="output">...</document> block. '
                                    "Do not call more tools. Do not add explanations."
                                ),
                            }
                        ],
                    }
                )
                reasoning.append("followup=empty_output_text_request_final_document")
                continue
            break

        for tool_call in tool_calls:
            found_tool = None
            for tool in tools:
                if tool_call.name == tool.description["name"]:
                    found_tool = tool
                    break

            if found_tool is None:
                raise RuntimeError(f"unable to find tool for {tool_call}")

            fulfilled_tool_calls.add(tool_call.call_id)
            result = found_tool.invoke(tool_call.arguments, tool_call.call_id)
            input_items.append(result)

    with open(os.path.join(output_dir, "debug_write_input.json"), "wt", encoding="utf-8") as f:
        json.dump(input_items, f, default=pydantic_encoder)

    with open(os.path.join(output_dir, "debug_write_output.txt"), "wt", encoding="utf-8") as f:
        f.write(response.output_text)

    with open(os.path.join(output_dir, "debug_write_reason.txt"), "wt", encoding="utf-8") as f:
        f.write("\n----------\n".join(reasoning))

    print("Generation finished successfully.")
    return response.output_text


def create_document(query: str | None, src_docs: list[str], target_doc: str):
    """ver2 검색 도구를 이용해 문서를 생성하고 이미지로 렌더링한다."""
    if query is None:
        query = "소스 문서 내용을 기반으로 작성해줘."

    datas = os.listdir("data")

    for src_doc in src_docs:
        if src_doc not in datas:
            raise FileNotFoundError(f"source document data/{src_doc} does not exist")

    if target_doc not in datas:
        raise FileNotFoundError(f"target document data/{target_doc} does not exist")

    output_dir_name = RESULT_OUTPUT_DIR_NAME or "__".join(src_docs)
    output_dir = os.path.join(RESULT_OUTPUT_ROOT, output_dir_name)
    os.makedirs(output_dir, exist_ok=True)

    layout_analyzer = LayoutAnalyzer()
    src_docs_parsed = [layout_analyzer(src_doc) for src_doc in src_docs]
    target_doc_parsed = layout_analyzer(target_doc)
    layout_analyzer.dispose()
    del layout_analyzer

    client = OpenAI(base_url=os.environ["OPENAI_BASE_URL"])

    target_doc_image_names = os.listdir(f"data/{target_doc}/")
    target_doc_image_names.sort()
    target_doc_images = [
        Image.open(f"data/{target_doc}/{x}")
        for x in target_doc_image_names
        if x.startswith("original")
    ]

    imagine = write_document(
        client,
        query,
        src_docs_parsed,
        target_doc_parsed,
        output_dir,
    )

    bboxes = [[block.bbox for block in page.blocks] for page in target_doc_parsed.pages]
    texts = [[cast(str | None, None) for _ in page.blocks] for page in target_doc_parsed.pages]
    htmls = [[cast(str | None, None) for _ in page.blocks] for page in target_doc_parsed.pages]
    line_heights = [
        [float(getattr(block, "line_height", 16.0)) for block in page.blocks]
        for page in target_doc_parsed.pages
    ]

    soup = BeautifulSoup(imagine.strip(), "lxml")
    document = soup.find("document")
    assert document is not None, (
        "LLM이 <document> 형식의 최종 문서를 생성하지 않았습니다. "
        "debug_write_output.txt와 debug_write_reason.txt를 확인하세요."
    )

    for page in document.find_all("page", recursive=False):
        for block in page.find_all("div", recursive=False):
            match = REGEX_DIV_ID.match(str(block.attrs["id"]))
            if match is None:
                continue

            block_page = int(match[1]) - 1
            block_idx = int(match[2]) - 1

            if len(texts) <= block_page or len(texts[block_page]) <= block_idx:
                print(f"[WARN] Invalid div: {block}")
                continue

            if block.find("img") is not None:
                print(f"[WARN] Ignoring div containing img: {block}")
                texts[block_page][block_idx] = "[이미지]"
                continue

            if block.find("table") is not None:
                table_root = deepcopy(block)
                table_root.attrs["id"] = "root"
                htmls[block_page][block_idx] = str(table_root)
                continue

            texts[block_page][block_idx] = block.text.strip()

    for i, img in enumerate(target_doc_images):
        valid_bboxes = []

        for bbox, text, html_fragment in zip(bboxes[i], texts[i], htmls[i]):
            if text is not None or html_fragment is not None:
                valid_bboxes.append(bbox)

        page_image = img.copy()
        for bbox in valid_bboxes:
            page_image = erase_bounding_box(page_image, bbox)

        page_image = render_boxes(
            page_image,
            bboxes[i],
            texts[i],
            htmls[i],
            line_heights[i],
        )

        page_image.save(os.path.join(output_dir, f"debug_finish_{i + 1}.png"))


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    option = 1

    if option == 0:
        create_document(None, ["financial2"], "financial1")
    elif option == 1:
        create_document(
            "financial2 문서를 기반으로 KMW 기업 분석 보고서를 작성해줘",
            ["financial2", "financial3"],
            "financial1",
        )
    elif option == 2:
        create_document(
            "삼성전자 관련 데일리 브리핑을 작성해줘 (시장 전체 말고 삼성전자만)",
            ["blog1", "financial1", "financial3"],
            "financial2",
        )
