import os
import re
import json
from pathlib import Path
from pydantic import BaseModel
from PIL import Image
from openai import OpenAI
from beartype import beartype
from bs4 import BeautifulSoup
from typing import Sequence, Any, cast
from openai.types.responses.response_input_param import ResponseInputParam

from llm2doc.analyze_layout import LayoutAnalyzer, ParsedDocument
from llm2doc.render_image import render_document, render_page, RenderedPage
from llm2doc.debug_trace import DecisionTracer, resolve_debug_trace
from llm2doc.tool_fetch_source_document import ToolFetchSourceDocument
from llm2doc.tool_search_source_document import ToolSearchSourceDocument


RESULT_OUTPUT_ROOT = "./"
RESULT_OUTPUT_DIR_NAME: str | None = "integrate2_news1_financial2"
PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
WORKSPACE_ROOT = PROJECT_ROOT.parent
SEMANTIC_ARTIFACTS_DIRNAME = "semantic_artifacts"


PROMPT_WRITE = """
You are an automated document writer.

# Task
You will be given a user query, a set of source documents, and a target document.

You have to write in the style and layout of the target document, but with materials from the source documents, respecting the user query.
In other words, keep the positions (divs) and structure of the target, but populate with source content.
You should follow the narrative flow of the target document.

Depending on the user query and/or style and layout of the target document, some of these source documents might be useless.
Use the language of target document, unless the user query says otherwise.

Source document is not present on this query directly, so use `search_source_document` tool to discover first-stage candidates.
The query should be in natural language. (e.g. "What best describes the document?")
The search tool returns candidate blocks, not final evidence. Use those candidates to decide which document/page to inspect next.

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

# Input format
The user query decides what the user wants.
This can be vague, and if so, you need to figure out what to write given the documents.

*Source* documents are what the user gave us as the source materials. Each source document will have a unique identifier (e.g., id="1").
You need to decide if each source documents are relevant to the user query individually.

# Output format
Write the new document as a single HTML-ish document, in same style and layout of *target* document.
You may use images present in any (source or target) document.
Wrap the output in <document id="output">...</document> tag just like the target document. The attribute `id` on div will be used to map them. Strictly keep the `output-page-x-block-y` format.
You can omit an div if you want to reuse what's in the source document. Reusing is resource-friendly, so try to reuse blocks whenever possible (as long as it doesn't affect the task).

Do not add any filler text, or they will be treated as part of the document you wrote.

## Hydration
In order to render each element, they will *individually* will go into hydration process.
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

# Actual input
Now this is the end of the guide.
Here is the actual input. Each input is wrapped inside <document>...</document> tag.

Each div block is positioned on the page via attribute `data-bbox`. It has format of [xmin, ymin, xmax, ymax] in 0-1000 relative scale. Each page has independent coordinates.

## Stylesheet
While the text below is not a complete HTML document (and should be not treated as such), here is the basic stylesheet for the document.

```css
document > page > div {{
  position: absolute;  /* Position and size is derived from the attribute `data-bbox` */
}}

document > page > div > p {{
  white-space: pre-wrap;
}}

table {{
  width: 100%;
}}
```

## User query
<query>
{query}
</query>

## Target document
{target}
"""

# target-page-1-block-1
REGEX_DIV_ID = re.compile(r"^(?:target-|output-)?page-([0-9]+)-block-([0-9]+)$")
REGEX_DOCUMENT_BLOCK = re.compile(r"<document\b[^>]*>.*?</document>", re.IGNORECASE | re.DOTALL)
REGEX_PAGE_BLOCK = re.compile(r"<page\b[^>]*>.*?</page>", re.IGNORECASE | re.DOTALL)
REGEX_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)

PROMPT_ANALYZE_TRACE = """
You have finished collecting evidence and are about to write the final document.

Output only a single JSON object. Do not use markdown fences.
Use exactly these top-level keys:
- query: string
- user_intent: string
- source_documents: array of {{document_id: string, used: boolean, reason: string}}
- evidence: array of {{document_id: string, page_id: integer, block_id: string, matched_via: array of strings, used_for: string, why_selected: string}}
- writing_strategy: array of strings
- uncertainties: array of strings

Rules:
- Use only information that appeared in search results or fetched source pages.
- Use exact document_id/page_id/block_id values when available.
- matched_via must include every retrieval channel that actually contributed.
- matched_via may contain only "semantic", "bm25", "entity", "block", "window", or "section".
- If you are uncertain, record it under uncertainties instead of inventing details.
- Include every provided source document in source_documents, even if it was not used.

Available source documents:
{source_documents}
""".strip()

PROMPT_FINAL_DOCUMENT = (
    "You have finished tool use. Now output only the final document as a single "
    '<document id="output">...</document> block. '
    "Do not call more tools. Do not add explanations, markdown fences, "
    "or any text before or after the document."
)

PROMPT_FINAL_DOCUMENT_RETRY = (
    "Your previous reply did not contain a valid <document>...</document> block. "
    'Output only the final document as a single <document id="output">...</document> block. '
    'The response must start with <document id="output"> and end with </document>. '
    "If you currently have only <page> blocks, wrap them in the required <document> block yourself. "
    "Do not call more tools. Do not add explanations, markdown fences, or any extra text."
)


def _semantic_artifact_dir(artifacts_root: Path, doc_id: str) -> Path:
    return artifacts_root / f"{doc_id}-00" / "01_reference"


def _has_semantic_artifact(artifacts_root: Path, doc_id: str) -> bool:
    artifact_dir = _semantic_artifact_dir(artifacts_root, doc_id)
    return (artifact_dir / "canonical_pages.json").exists() and (artifact_dir / "semantic_overlay.json").exists()


def _semantic_visualization_path(artifacts_root: Path, doc_id: str) -> Path:
    return _semantic_artifact_dir(artifacts_root, doc_id) / "reference_visualization.html"


def ensure_semantic_artifacts(
    doc_ids: Sequence[str],
    artifacts_root: Path,
    tracer: DecisionTracer | None = None,
) -> bool:
    from llm2doc.artifact.semantic.pipeline.reference_pipeline import parse_reference
    from llm2doc.artifact.semantic.semantic.semantic_types import SemanticConfig

    created_any = False

    for doc_id in doc_ids:
        if _has_semantic_artifact(artifacts_root, doc_id):
            if tracer is not None:
                tracer.event(
                    "semantic_artifacts",
                    "artifact_reused",
                    {"document_id": doc_id, "artifact_dir": str(_semantic_artifact_dir(artifacts_root, doc_id))},
                )
            continue

        if tracer is not None:
            tracer.event(
                "semantic_artifacts",
                "artifact_generation_started",
                {"document_id": doc_id, "artifact_dir": str(_semantic_artifact_dir(artifacts_root, doc_id))},
            )

        parse_reference(
            job_id=f"{doc_id}-00",
            reference_path=doc_id,
            artifacts_root=str(artifacts_root),
            semantic_config=SemanticConfig(mode="qwen", runtime="api"),
            llm2doc_root=str(PROJECT_ROOT),
        )
        created_any = True

        if tracer is not None:
            tracer.event(
                "semantic_artifacts",
                "artifact_generation_completed",
                {"document_id": doc_id, "artifact_dir": str(_semantic_artifact_dir(artifacts_root, doc_id))},
            )

    return created_any


def ensure_semantic_visualizations(
    doc_ids: Sequence[str],
    artifacts_root: Path,
    tracer: DecisionTracer | None = None,
) -> list[Path]:
    from llm2doc.artifact.semantic.visualization.visualize import render_reference_visualization

    visualization_paths: list[Path] = []

    for doc_id in doc_ids:
        artifact_dir = _semantic_artifact_dir(artifacts_root, doc_id)
        if not artifact_dir.exists():
            continue

        output_path = _semantic_visualization_path(artifacts_root, doc_id)
        render_reference_visualization(
            artifact_dir=str(artifact_dir),
            output_path=str(output_path),
        )
        visualization_paths.append(output_path)

        if tracer is not None:
            tracer.event(
                "semantic_artifacts",
                "visualization_ready",
                {
                    "document_id": doc_id,
                    "visualization_path": str(output_path),
                },
            )

    return visualization_paths


def pydantic_encoder(obj):
    """Pydantic 모델을 debug JSON 파일로 저장할 수 있게 변환한다."""
    if isinstance(obj, BaseModel):
        return obj.model_dump()  # converts the model to a standard dict
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def extract_document_block(text: str) -> str | None:
    """응답 텍스트 안에서 가장 먼저 등장한 `<document>` 블록을 추출한다."""
    match = REGEX_DOCUMENT_BLOCK.search(text)
    if match is None:
        json_payload = extract_json_object(text)
        if isinstance(json_payload, dict):
            for key in ("document", "output", "content", "html"):
                candidate = json_payload.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    extracted = extract_document_block(candidate)
                    if extracted is not None:
                        return extracted

        soup = BeautifulSoup(text, "lxml")
        document = soup.find("document")
        if document is not None:
            return str(document)

        pages = soup.find_all("page")
        if pages:
            page_html = "\n".join(str(page) for page in pages)
            return f'<document id="output">\n{page_html}\n</document>'

        page_matches = REGEX_PAGE_BLOCK.findall(text)
        if page_matches:
            return '<document id="output">\n' + "\n".join(page_matches) + "\n</document>"

        return None
    return match.group(0)


def response_to_jsonable(response: Any) -> Any:
    try:
        return json.loads(response.model_dump_json())
    except Exception:
        return {"output_text": getattr(response, "output_text", "")}


def extract_response_text(response: Any) -> str:
    """Extracts the actual text content from the Response object, handling reasoning blocks properly."""
    try:
        parts = []
        if hasattr(response, "output") and isinstance(response.output, list):
            for item in response.output:
                if getattr(item, "type", "") == "message" and getattr(item, "content", None) is not None:
                    for c in item.content:
                        if getattr(c, "type", "") == "output_text" and getattr(c, "text", None) is not None:
                            parts.append(c.text)

        text = "".join(parts).strip()
        if text:
            return text
    except Exception:
        pass

    return getattr(response, "output_text", "").strip()


def extract_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    fence_match = REGEX_JSON_FENCE.fullmatch(stripped)
    if fence_match is not None:
        stripped = fence_match.group(1).strip()

    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    return None


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    return str(value).strip()


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return False


def _coerce_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return 0
    return 0


def _coerce_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result = [_coerce_str(item) for item in value]
    return [item for item in result if item]


def _normalize_matched_via(value: Any) -> list[str]:
    if isinstance(value, str):
        values = [_coerce_str(value)]
    else:
        values = _coerce_str_list(value)

    deduped: list[str] = []
    seen: set[str] = set()
    for item in values:
        if not item or item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def normalize_analysis_payload(
    payload: dict[str, Any] | None,
    *,
    query: str,
    source_doc_ids: Sequence[str],
) -> dict[str, Any]:
    payload = payload or {}

    parsed_source_documents: dict[str, dict[str, Any]] = {}
    for item in payload.get("source_documents", []):
        if not isinstance(item, dict):
            continue
        document_id = _coerce_str(item.get("document_id"))
        if not document_id:
            continue
        parsed_source_documents[document_id] = {
            "document_id": document_id,
            "used": _coerce_bool(item.get("used")),
            "reason": _coerce_str(item.get("reason")),
        }

    source_documents: list[dict[str, Any]] = []
    for document_id in source_doc_ids:
        source_documents.append(
            parsed_source_documents.get(
                document_id,
                {
                    "document_id": document_id,
                    "used": False,
                    "reason": "",
                },
            )
        )

    evidence: list[dict[str, Any]] = []
    for item in payload.get("evidence", []):
        if not isinstance(item, dict):
            continue
        document_id = _coerce_str(item.get("document_id"))
        block_id = _coerce_str(item.get("block_id"))
        if not document_id or not block_id:
            continue
        evidence.append(
            {
                "document_id": document_id,
                "page_id": _coerce_int(item.get("page_id")),
                "block_id": block_id,
                "matched_via": _normalize_matched_via(item.get("matched_via")),
                "used_for": _coerce_str(item.get("used_for")),
                "why_selected": _coerce_str(item.get("why_selected")),
            }
        )

    return {
        "query": _coerce_str(payload.get("query")) or query,
        "user_intent": _coerce_str(payload.get("user_intent")),
        "source_documents": source_documents,
        "evidence": evidence,
        "writing_strategy": _coerce_str_list(payload.get("writing_strategy")),
        "uncertainties": _coerce_str_list(payload.get("uncertainties")),
    }


def maybe_generate_analysis(
    client: OpenAI,
    input_items: ResponseInputParam,
    query: str,
    source_doc_ids: Sequence[str],
    tracer: DecisionTracer,
    *,
    component: str,
) -> dict[str, Any] | None:
    if not tracer.enabled:
        return None

    tracer.event(
        component,
        "analysis_requested",
        {"source_documents": list(source_doc_ids)},
    )
    analysis_prompt = PROMPT_ANALYZE_TRACE.format(source_documents=", ".join(source_doc_ids))
    response = client.responses.create(
        model=os.environ["OPENAI_MODEL"],
        input=input_items
        + [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": analysis_prompt}],
            }
        ],
    )
    tracer.save_json("llm/analysis_response.json", response_to_jsonable(response))

    analysis = normalize_analysis_payload(
        extract_json_object(extract_response_text(response)),
        query=query,
        source_doc_ids=source_doc_ids,
    )
    tracer.save_json("analysis.json", analysis)
    tracer.event(
        component,
        "analysis_saved",
        {
            "source_document_count": len(analysis["source_documents"]),
            "evidence_count": len(analysis["evidence"]),
        },
    )
    return analysis


def request_final_document(
    client: OpenAI,
    input_items: ResponseInputParam,
    tracer: DecisionTracer,
    *,
    component: str,
    output_dir: str | None = None,
) -> str:
    final_input = list(input_items)
    prompt_text = PROMPT_FINAL_DOCUMENT
    last_output_text = ""

    for attempt in range(1, 6):
        tracer.event(component, "final_document_requested", {"attempt": attempt})
        final_input.append(
            {
                "role": "user",
                "content": [{"type": "input_text", "text": prompt_text}],
            }
        )
        response = client.responses.create(
            model=os.environ["OPENAI_MODEL"],
            input=final_input,
        )
        tracer.save_json("llm/final_document_response.json", response_to_jsonable(response))

        output_text = extract_response_text(response)
        last_output_text = output_text
        if output_dir is not None:
            with open(os.path.join(output_dir, "debug_write_output.txt"), "wt", encoding="utf-8") as f:
                f.write(output_text)

        extracted_document = extract_document_block(output_text)
        if extracted_document is not None:
            if output_dir is not None:
                with open(os.path.join(output_dir, "debug_write_output.txt"), "wt", encoding="utf-8") as f:
                    f.write(extracted_document)
            tracer.event(
                component,
                "final_document_saved",
                {"attempt": attempt, "chars": len(extracted_document)},
            )
            return extracted_document

        tracer.event(
            component,
            "final_document_invalid",
            {"attempt": attempt, "preview": output_text[:500]},
        )
        final_input += response.output  # type: ignore
        prompt_text = PROMPT_FINAL_DOCUMENT_RETRY

    if output_dir is not None and last_output_text:
        with open(os.path.join(output_dir, "debug_write_output.txt"), "wt", encoding="utf-8") as f:
            f.write(last_output_text)
    raise RuntimeError("LLM did not return a valid <document> block after retries.")


@beartype
def write_document(
    client: OpenAI,
    query: str,
    src_docs: Sequence[ParsedDocument],
    target_doc: ParsedDocument,
    output_dir: str,
    semantic_artifacts_root: Path,
    tracer: DecisionTracer,
    *,
    component: str,
    force_rebuild_search_index: bool = False,
) -> str:
    """LLM과 도구 호출 루프를 돌며 최종 문서 블록을 생성한다."""
    imagine_prompt = PROMPT_WRITE.strip().format(
        query=query.strip().replace("&", "&amp;").replace("<", "&gt;").replace(">", "&lt;"),
        target=target_doc.to_sturctured_html(doc_id="target"),
    )

    with open(os.path.join(output_dir, "debug_write_input.txt"), "wt", encoding="utf-8") as f:
        f.write(imagine_prompt)

    # 모델이 사용할 수 있는 도구는 "원문 검색"과 "특정 페이지 조회" 두 종류다.
    tools = [
        ToolFetchSourceDocument(src_docs),
        ToolSearchSourceDocument(
            [x.id for x in src_docs],
            client=client,
            tracer=tracer,
            artifacts_root=semantic_artifacts_root,
            force_rebuild=force_rebuild_search_index,
        ),
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
        tracer.save_json(
            f"llm/tool_loop_response_{response_cnt}.json",
            response_to_jsonable(response),
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

        input += response.output  # type: ignore

        tool_calls = [
            item for item in response.output if item.type == "function_call" and item.call_id not in fulfiled_tool_calls
        ]
        if len(tool_calls) == 0:
            break

        # 모델이 요청한 도구를 실제 파이썬 객체에 매핑해 실행한다.
        for tool_call in tool_calls:
            tracer.event(
                component,
                "tool_requested",
                {
                    "tool": tool_call.name,
                    "call_id": tool_call.call_id,
                    "arguments": tool_call.arguments,
                },
            )
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
            tracer.event(
                component,
                "tool_result",
                {
                    "tool": tool_call.name,
                    "call_id": tool_call.call_id,
                    "output_preview": str(result.get("output", ""))[:500],
                },
            )

    maybe_generate_analysis(
        client,
        input,
        query,
        [doc.id for doc in src_docs],
        tracer,
        component=component,
    )
    final_document_text = request_final_document(
        client,
        input,
        tracer,
        component=component,
        output_dir=output_dir,
    )

    with open(os.path.join(output_dir, "debug_write_input.json"), "wt", encoding="utf-8") as f:
        json.dump(input, f, default=pydantic_encoder)

    with open(os.path.join(output_dir, "debug_write_output.txt"), "wt", encoding="utf-8") as f:
        f.write(final_document_text)

    with open(os.path.join(output_dir, "debug_write_reason.txt"), "wt", encoding="utf-8") as f:
        f.write("\n----------\n".join(reasoning))

    print("Generation finished successfully.")

    return final_document_text


@beartype
def create_document(
    query: str | None,
    src_docs: list[str],
    target_doc: str,
    debug_trace: bool | None = None,
):
    """문서 생성부터 결과 이미지 렌더링까지 전체 작업을 수행한다."""
    if query is None:
        query = "소스 문서 내용을 기반으로 작성해줘."

    # 필요한 파일들이 존재하는지 확인
    # 입력으로 받은 문서 ID가 실제 `data` 폴더 안에 존재하는지 먼저 확인한다.
    datas = os.listdir("data")

    for src_doc in src_docs:
        if src_doc not in datas:
            raise FileNotFoundError(f"source document data/{src_doc} does not exist")

    if target_doc not in datas:
        raise FileNotFoundError(f"target document data/{target_doc} does not exist")

    output_dir_name = RESULT_OUTPUT_DIR_NAME or f"{'_'.join(src_docs)}_{target_doc}"
    output_dir = os.path.join(RESULT_OUTPUT_ROOT, output_dir_name)
    os.makedirs(output_dir, exist_ok=True)
    semantic_artifacts_root = Path(output_dir) / SEMANTIC_ARTIFACTS_DIRNAME
    tracer = DecisionTracer.create(
        output_dir,
        enabled=resolve_debug_trace(debug_trace),
    )
    tracer.event(
        "create_document",
        "run_started",
        {
            "query": query,
            "src_docs": src_docs,
            "target_doc": target_doc,
            "output_dir": output_dir,
        },
    )
    artifacts_created = False
    semantic_visualization_paths: list[Path] = []

    try:
        # 문서 불러와서 파싱
        # 소스/타깃 문서를 모두 OCR 구조로 로딩한다.
        artifacts_created = ensure_semantic_artifacts(src_docs, semantic_artifacts_root, tracer)
        semantic_visualization_paths = ensure_semantic_visualizations(
            src_docs,
            semantic_artifacts_root,
            tracer,
        )
        layout_analyzer = LayoutAnalyzer()

        src_docs_parsed = []

        for src_doc in src_docs:
            document = layout_analyzer(src_doc)
            src_docs_parsed.append(document)

        target_doc_parsed = layout_analyzer(target_doc)

        tracer.event(
            "create_document",
            "layout_loaded",
            {
                "source_docs": [{"document_id": doc.id, "page_count": len(doc.pages)} for doc in src_docs_parsed],
                "target_doc": {
                    "document_id": target_doc_parsed.id,
                    "page_count": len(target_doc_parsed.pages),
                },
            },
        )

        layout_analyzer.dispose()
        del layout_analyzer

        # LLM에게 문서를 작성시킴
        # 문서 생성 자체는 Responses API를 쓰는 LLM 호출 루프에서 처리한다.
        client = OpenAI(base_url=os.environ["OPENAI_BASE_URL"])

        target_doc_image_names = os.listdir(f"data/{target_doc}/")
        target_doc_image_names.sort()
        target_doc_images = [
            Image.open(f"data/{target_doc}/{x}") for x in target_doc_image_names if x.startswith("original")
        ]

        imagine = write_document(
            client,
            query,
            src_docs_parsed,
            target_doc_parsed,
            output_dir,
            semantic_artifacts_root,
            tracer,
            component="create_document",
            force_rebuild_search_index=artifacts_created,
        )

        # 작성한 문서를 렌더링함
        texts = [[cast(str | None, None) for _ in x.blocks] for x in target_doc_parsed.pages]
        htmls = [[cast(str | None, None) for _ in x.blocks] for x in target_doc_parsed.pages]

        # LLM이 반환한 최종 문서 문자열에서 블록별 텍스트/테이블 HTML을 추출한다.
        soup = BeautifulSoup(imagine.strip(), "lxml")
        document = soup.find("document")
        assert document is not None, (
            "LLM이 <document> 형식의 최종 문서를 생성하지 않았습니다. "
            "debug_write_output.txt와 debug_write_reason.txt를 확인하세요."
        )

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
                    # texts[block_page][block_idx] = "[이미지]"
                    continue

                htmls[block_page][block_idx] = block.decode_contents()

        tracer.event(
            "create_document",
            "render_started",
            {"page_count": len(target_doc_images)},
        )

        rendered_pages: list[RenderedPage] = []

        for i, (page, img) in enumerate(zip(target_doc_parsed.pages, target_doc_images)):
            rendered_pages.append(render_page(page, img, htmls[i], f"page-{i + 1}"))

        rendered_doc = render_document(rendered_pages)
        rendered_doc_json = rendered_doc.model_dump_json()
        with open(os.path.join(output_dir, "debug_finish.json"), "wt", encoding="utf-8") as f:
            f.write(rendered_doc_json)

        tracer.event(
            "create_document",
            "render_completed",
            {"page_count": len(target_doc_images)},
        )
        tracer.event(
            "create_document",
            "run_completed",
            {"output_dir": output_dir},
        )
        result_paths = [
            Path(output_dir) / "debug_write_output.txt",
            Path(output_dir) / "debug_finish.json",
            *semantic_visualization_paths,
        ]
        existing_result_paths = [path.resolve() for path in result_paths if path.exists()]
        if existing_result_paths:
            print("Generated result files:")
            for path in existing_result_paths:
                print(str(path))

        return rendered_doc

    except Exception as exc:
        tracer.event(
            "create_document",
            "run_failed",
            {"error": str(exc), "error_type": type(exc).__name__},
        )
        raise
