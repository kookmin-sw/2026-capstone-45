import json
from pathlib import Path
from typing import List, Optional

from PIL import Image

from .types import EnginePage, PageSource, RawEngineBlock
from .utils import clean_text, normalize_bbox, union_bbox


def _load_json(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _infer_page_size(page_source: PageSource, fallback_blocks: List[List[int]]) -> List[int]:
    image_candidates = [
        page_source.surya_image_path,
        page_source.paddle_visualization_path,
        page_source.dolphin_layout_path,
    ]
    for candidate in image_candidates:
        if candidate and Path(candidate).exists():
            with Image.open(candidate) as image:
                return [image.width, image.height]
    if fallback_blocks:
        bbox = union_bbox(fallback_blocks)
        return [max(1, bbox[2]), max(1, bbox[3])]
    return [1, 1]


def load_dolphin_page(page_source: PageSource) -> Optional[EnginePage]:
    if not page_source.dolphin_json_path or not Path(page_source.dolphin_json_path).exists():
        return None
    payload = _load_json(page_source.dolphin_json_path)
    fallback_boxes = [item.get("bbox", [0, 0, 0, 0]) for item in payload]
    width, height = _infer_page_size(page_source, fallback_boxes)
    raw_blocks = []
    for item in payload:
        bbox = item.get("bbox", [0, 0, 0, 0])
        raw_blocks.append(
            RawEngineBlock(
                engine="dolphin",
                page=page_source.page_number,
                raw_label=item.get("label", "unknown"),
                text=clean_text(item.get("text", "")),
                bbox_px=[int(value) for value in bbox],
                bbox_norm=normalize_bbox(bbox, width, height),
                reading_order=item.get("reading_order"),
                polygon=[],
                tags=list(item.get("tags", [])),
                raw_confidence=None,
            )
        )
    return EnginePage(
        engine="dolphin",
        page=page_source.page_number,
        sample_id=page_source.sample_id,
        width=width,
        height=height,
        raw_blocks=raw_blocks,
        source_paths={"json": page_source.dolphin_json_path},
        metadata={"markdown_path": page_source.dolphin_markdown_path},
    )


def load_paddle_page(page_source: PageSource) -> Optional[EnginePage]:
    if not page_source.paddle_json_path or not Path(page_source.paddle_json_path).exists():
        return None
    payload = _load_json(page_source.paddle_json_path)
    width = int(payload.get("width") or 1)
    height = int(payload.get("height") or 1)
    raw_blocks = []
    for item in payload.get("parsing_res_list", []):
        bbox = item.get("block_bbox", [0, 0, 0, 0])
        polygon = item.get("block_polygon_points", [])
        raw_blocks.append(
            RawEngineBlock(
                engine="paddle",
                page=page_source.page_number,
                raw_label=item.get("block_label", "unknown"),
                text=clean_text(item.get("block_content", "")),
                bbox_px=[int(value) for value in bbox],
                bbox_norm=normalize_bbox(bbox, width, height),
                reading_order=item.get("block_order"),
                polygon=polygon,
                tags=[],
                raw_confidence=None,
            )
        )
    return EnginePage(
        engine="paddle",
        page=page_source.page_number,
        sample_id=page_source.sample_id,
        width=width,
        height=height,
        raw_blocks=raw_blocks,
        source_paths={"json": page_source.paddle_json_path},
        metadata={
            "markdown_path": page_source.paddle_markdown_path,
            "visualization_path": page_source.paddle_visualization_path,
        },
    )
