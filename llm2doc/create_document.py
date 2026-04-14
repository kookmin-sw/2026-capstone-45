import os
import re
import json
from dotenv import load_dotenv
from copy import deepcopy
from pydantic import BaseModel
from PIL import Image
from openai import OpenAI
from beartype import beartype
from bs4 import BeautifulSoup
from typing import Sequence, List, Any, cast
from openai.types.responses.response_input_param import ResponseInputParam

from .analyze_layout import LayoutAnalyzer, ParsedDocument
from .render_image import render_boxes, erase_bounding_box
from .util import image_as_data_uri
from .tool_fetch_source_document import ToolFetchSourceDocument
from .tool_search_source_document import ToolSearchSourceDocument
from .tool_ask_user_question import ToolAskUserQuestion


PROMPT_WRITE = """
You are an automated document writer.

# Task
You will be given a user query, a set of source documents, and a target document.

You have to write in the style and layout of the target document, but with materials from the source documents, respecting the user query.
In other words, keep the positions (divs) and structure of the target, but populate with source content.
You should follow the narrative flow of the target document.

Depending on the user query and/or style and layout of the target document, some of these source documents might be useless.
Use the language of target document, unless the user query says otherwise.

Source document is not present on this query directly, so use `search_source_document` tool to discover them.
The query should be in natural language. (e.g. "What best describes the document?")

Once discovered, source document can be fetched using `fetch_source_document` tool.

## Tips
* NEVER fabricate a new information on your own. Everything MUST be from the source document.
* Strictly preserve the micro-formatting of the target block you are filling.
  * Examples:
  * If the target block is a continuous text paragraph, write a continuous text paragraph.
  * If the target is a bulleted list, write a bulleted list.
  * If the source is a paragraph but the target is a table, you must extract the data into a table.
  * Match the tone (말투) of the target block. For instance, do not modify "-음." into "-입니다." or vise versa.
* The goal is to fill the same amount of 'real estate' on each block. Use the target as a template for length, but don't feel obligated to hit an exact line count if the flow is better slightly shorter or longer.
* Match the logical progression and rhetorical purpose of the target document. Keep the argument structure (e.g., Claim -> Evidence -> Summary) of the target.
* Because both source and target are processed with OCR, it may contain typos or inconsistent line breaks. Try to mitigate them.
* Understand that *contents* of the target document has nothing to do with what needs to be written. They are solely for style reference.

## Tools
When using search tool, use natural language to query. For instance, "What is lorem ipsum?" is better than "loerm ipsum origin root description".

Think again after each tool call, and especially before you write your final answer.

Note that user cannot read the generated document until you finish. That means you must NOT ask the user regarding what you wrote.

# Input format
The user query decides what the user wants.
This can be vague, and if so, you need to figure out what to write given the documents.

*Source* documents are what the user gave us as the source materials. Each source document will have a unique identifier (e.g., id="1").
You need to decide if each source documents are relevant to the user query individually.

Each input is wrapped inside <document>...</document> tag.
Each div block is positioned on the page via attribute `data-bbox`.
It has format of [xmin, ymin, xmax, ymax] in 0-1000 relative scale.
Each page has independent coordinates.

## Stylesheet
While the input is not a complete HTML document (and should be not treated as such), here is the basic stylesheet for the document.

```css
document > page > div {{
  position: absolute;  /* Position and size is derived from the attribute `data-bbox` */

  /* Value below are autodetected from OCR result */
  line-height: (auto)px;
  font-family: (auto);
  font-size: (auto)px;
  color: (auto);
  background-color: (auto);
}}

document > page > div > p {{
  white-space: pre-wrap;
}}

table {{
  width: 100%;
}}
```

# Output format
Write the new document as a single HTML-ish document, in same style and layout of *target* document.
You may use images present in any (source or target) document.
Wrap the output in <document id="output">...</document> tag just like the target document. The attribute `id` on div will be used to map them. Strictly keep the `output-page-x-block-y` format.
You can omit an div if you want to reuse what's in the source document. Reusing is resource-friendly, so try to reuse blocks whenever possible (as long as it doesn't affect the task).

Do not add any filler text, or they will be treated as part of the document you wrote.

## Hydration
In order to render each block, they will go into hydration process *individually*.
1. The div is wrapped with a body tag to form full HTML document.
2. font-size of html tag is set to that of target document, so that 1rem = font size in target document.
3. The body size is set to appropriate pixel.
4. The div is set to have take full height and width.

Therefore, you should style the element to best match the target document.
Use inline style attribute. Tailwind does NOT work.
Examples include:
* Setting color of the text.
* 'text-align' to center the text.
* Flexbox to vertically center the text or table.

# The input
## User query
<query>
{query}
</query>

## Target document
{target}
"""

# target-page-1-block-1
REGEX_DIV_ID = re.compile(r"^(?:target-|output-)?page-([0-9]+)-block-([0-9]+)$")


def pydantic_encoder(obj):
    """Tells json.dumps how to handle Pydantic models."""
    if isinstance(obj, BaseModel):
        return obj.model_dump()  # converts the model to a standard dict
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


@beartype
def write_document(
    client: OpenAI,
    query: str,
    src_docs: Sequence[ParsedDocument],
    target_doc: ParsedDocument,
) -> str:
    imagine_prompt = PROMPT_WRITE.strip().format(
        query=query,
        target=target_doc.to_sturctured_html(doc_id="target"),
    )

    with open("debug_write_input.txt", "wt", encoding="utf-8") as f:
        f.write(imagine_prompt)

    tools = [
        ToolFetchSourceDocument(src_docs),
        ToolSearchSourceDocument([x.id for x in src_docs]),
        ToolAskUserQuestion(),
    ]

    reasoning = cast(list[str], [])
    fulfiled_tool_calls: set[str] = set()

    input: ResponseInputParam = [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": imagine_prompt},
            ],
        }
    ]

    response_cnt = 0

    while True:
        response = client.responses.create(
            model=os.environ["OPENAI_MODEL"],
            input=input,
            tools=[x.description for x in tools],
            tool_choice="auto",
        )
        response_cnt += 1

        for item in response.output:
            try:
                if item.type == "reasoning" and item.content is not None:
                    for content in item.content:
                        reasoning.append(content.text)
                elif item.type == "function_call" and item.arguments is not None:
                    reasoning.append(f"function_call={item.name} {item.arguments}")
            except Exception:
                pass

        input += response.output  # type: ignore

        tool_calls = [
            item for item in response.output if item.type == "function_call" and item.call_id not in fulfiled_tool_calls
        ]
        if len(tool_calls) == 0:
            break

        for tool_call in tool_calls:
            found = False
            for tool in tools:
                if tool_call.name == tool.description["name"]:
                    found = True
                    break

            if not found:
                raise RuntimeError(f"unable to find tool for {tool_call}")

            fulfiled_tool_calls.add(tool_call.call_id)
            result = tool.invoke(tool_call.arguments, tool_call.call_id)
            input.append(result)

    with open("debug_write_input.json", "wt", encoding="utf-8") as f:
        json.dump(input, f, default=pydantic_encoder)

    with open("debug_write_output.txt", "wt", encoding="utf-8") as f:
        f.write(response.output_text)

    with open("debug_write_reason.txt", "wt", encoding="utf-8") as f:
        f.write("\n----------\n".join(reasoning))

    print("Generation finished successfully.")

    return response.output_text


@beartype
def create_document(query: str | None, src_docs: list[str], target_doc: str):
    if query is None:
        query = "소스 문서 내용을 기반으로 작성해줘."

    # 필요한 파일들이 존재하는지 확인
    datas = os.listdir("data")

    for src_doc in src_docs:
        if src_doc not in datas:
            raise FileNotFoundError(f"source document data/{src_doc} does not exist")

    if target_doc not in datas:
        raise FileNotFoundError(f"target document data/{target_doc} does not exist")

    # 문서 불러와서 파싱
    layout_analyzer = LayoutAnalyzer()

    src_docs_parsed = []

    for src_doc in src_docs:
        document = layout_analyzer(src_doc)
        src_docs_parsed.append(document)

    target_doc_parsed = layout_analyzer(target_doc)

    layout_analyzer.dispose()
    del layout_analyzer

    # LLM에게 문서를 작성시킴
    client = OpenAI(base_url=os.environ["OPENAI_BASE_URL"])

    target_doc_image_names = os.listdir(f"data/{target_doc}/")
    target_doc_image_names.sort()
    target_doc_images = [
        Image.open(f"data/{target_doc}/{x}") for x in target_doc_image_names if x.startswith("original")
    ]

    # imagine = write_document(client, query, src_docs_parsed, target_doc_parsed)
    with open("debug_write_output.txt", "rt", encoding="utf-8") as f:
        imagine = f.read()

    # 작성한 문서를 렌더링함
    bboxes = [[y.bbox for y in x.blocks] for x in target_doc_parsed.pages]
    texts = [[cast(str | None, None) for _ in x.blocks] for x in target_doc_parsed.pages]
    htmls = [[cast(str | None, None) for _ in x.blocks] for x in target_doc_parsed.pages]

    soup = BeautifulSoup(imagine.strip(), "lxml")
    document = soup.find("document")
    assert document is not None, "LLM이 문서를 생성하지 않았습니다"

    for i, page in enumerate(document.find_all("page", recursive=False)):
        for j, block in enumerate(page.find_all("div", recursive=False)):
            m = REGEX_DIV_ID.match(str(block.attrs["id"]))
            if m is None:
                continue

            block_page = int(m[1]) - 1
            block_idx = int(m[2]) - 1

            if len(texts) <= block_page or len(texts[block_page]) <= block_idx:
                print(f"[WARN] Invalid div: {block}")
                continue

            if block.find("img") is not None:
                print(f"[WARN] Ignoring div containing img: {block}")
                texts[block_page][block_idx] = "[이미지]"
                continue

            if block.find("table") is not None:
                block = deepcopy(block)
                block.attrs["id"] = "root"
                htmls[block_page][block_idx] = str(block)
                continue

            texts[block_page][block_idx] = block.text.strip()

    for i, img in enumerate(target_doc_images):
        valid_bboxes = []

        for bbox, text, html in zip(bboxes[i], texts[i], htmls[i]):
            if text is not None or html is not None:
                valid_bboxes.append(bbox)

        img = img.copy()
        for bbox in valid_bboxes:
            img = erase_bounding_box(img, bbox)

        img = render_boxes(
            img,
            bboxes[i],
            texts[i],
            htmls[i],
            target_doc_parsed.pages[i].blocks,
        )

        img.save(f"debug_finish_{i + 1}.png")
