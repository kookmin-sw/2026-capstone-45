import json
from pathlib import Path

from ..common.types import EnginePage, PageSource, RawEngineBlock
from ..common.utils import clean_text, normalize_bbox


def _load_json(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_paddle_page(page_source: PageSource, *, json_path: str) -> EnginePage:
    payload = _load_json(json_path)
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
        source_paths={"json": json_path, "image": page_source.image_path or ""},
        metadata={},
    )
