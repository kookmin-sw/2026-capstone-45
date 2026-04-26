import argparse
import json
import pickle
from pathlib import Path
from typing import Any


def _block_to_dict(block: Any) -> dict[str, Any]:
    return {
        "label": getattr(block, "label", None),
        "bbox": getattr(block, "bbox", None),
        "content": getattr(block, "content", None),
        "is_html": getattr(block, "is_html", None),
        "is_image": getattr(block, "is_image", None),
        "is_text": getattr(block, "is_text", None),
        "style": getattr(block, "style", None),
    }


def _page_to_dict(page: Any, page_index: int) -> dict[str, Any]:
    return {
        "page": page_index,
        "width": getattr(page, "width", None),
        "height": getattr(page, "height", None),
        "blocks": [_block_to_dict(block) for block in getattr(page, "blocks", [])],
    }


def _document_to_dict(doc: Any) -> dict[str, Any]:
    return {
        "id": getattr(doc, "id", None),
        "pages": [
            _page_to_dict(page, page_index + 1)
            for page_index, page in enumerate(getattr(doc, "pages", []))
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dump llm2doc layout.pickle to readable JSON."
    )
    parser.add_argument("pickle_path", help="Path to layout.pickle")
    parser.add_argument(
        "--output",
        help="Optional output JSON path. Defaults to <pickle>.json",
    )
    args = parser.parse_args()

    pickle_path = Path(args.pickle_path)
    output_path = (
        Path(args.output)
        if args.output
        else pickle_path.with_suffix(pickle_path.suffix + ".json")
    )

    with pickle_path.open("rb") as f:
        doc = pickle.load(f)

    data = _document_to_dict(doc)
    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
