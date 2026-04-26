import re

from pydantic import BaseModel


REGEX_NEWLINE = re.compile(r"[\r\n]+")


class OCRBlock(BaseModel):
    label: str
    content: str
    bbox: list[int]

    @property
    def is_text(self) -> bool:
        return not (self.is_image or self.is_html)

    @property
    def is_image(self) -> bool:
        return self.label in ("image", "chart")

    @property
    def is_html(self) -> bool:
        return self.label in ("table",)

    def to_structured_html(self, page: "OCRPage", indent: int = 0, block_id: str | None = None) -> str:
        result = []

        bbox = [
            self.bbox[0] * 1000 // page.width,
            self.bbox[1] * 1000 // page.height,
            self.bbox[2] * 1000 // page.width,
            self.bbox[3] * 1000 // page.height,
        ]
        bbox_str = ", ".join([str(x) for x in bbox])

        result.append(" " * indent)
        result.append(f'<div id="{block_id}" data-bbox="[{bbox_str}]">\n')

        if self.is_text:
            for line in REGEX_NEWLINE.split(self.content.strip()):
                result.append(" " * indent)
                result.append("  <p>")
                result.append(line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
                result.append("</p>\n")
        elif self.is_image:
            result.append(" " * indent)
            result.append(f'  <img src="/{block_id}/image">\n')
        elif self.is_html:
            result.append(" " * indent)
            result.append("  ")
            result.append(self.content)
            result.append("\n")
        else:
            print("[WARN] Block has no is_* directive")

        result.append(" " * indent)
        result.append("</div>")

        return "".join(result)


class OCRPage(BaseModel):
    width: int
    height: int
    blocks: list[OCRBlock]
    json: str
    markdown: str

    def __str__(self):
        content = "\n\n".join([f"Block #{i}\n{blk}" for i, blk in enumerate(self.blocks)])
        return f"#####\n{content}\n#####"

    def to_structured_html(self, indent: int = 0, page_id: str | None = None) -> str:
        result = []
        result.append(" " * indent)
        result.append(f'<page id="{page_id}">\n')

        for i, block in enumerate(self.blocks):
            if page_id is None:
                block_id = f"block-{i + 1}"
            else:
                block_id = f"{page_id}-block-{i + 1}"

            result.append(block.to_structured_html(self, indent=indent + 2, block_id=block_id))
            result.append("\n")

        result.append(" " * indent)
        result.append("</page>\n")

        return "".join(result)


class OCRArtifact(BaseModel):
    pages: list[OCRPage]

    def to_sturctured_html(self, indent: int = 0, doc_id: str | None = None) -> str:
        result = []

        result.append(" " * indent)
        if doc_id is None:
            result.append("<document>\n")
        else:
            result.append(f'<document id="{doc_id}">\n')

        for i, page in enumerate(self.pages):
            if doc_id is None:
                page_id = f"page-{i + 1}"
            else:
                page_id = f"{doc_id}-page-{i + 1}"

            result.append(page.to_structured_html(indent=indent + 2, page_id=page_id))
            result.append("\n")

        result.append(" " * indent)
        result.append("</document>")

        return "".join(result)
