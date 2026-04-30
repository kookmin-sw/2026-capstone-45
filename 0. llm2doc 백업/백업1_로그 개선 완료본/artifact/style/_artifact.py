from pydantic import BaseModel


class BlockStyle(BaseModel):
    line_count: int
    """줄 수"""

    line_height: float
    """pixels"""

    font_family: str
    """path to the font"""

    color: tuple[int, ...]
    """(r, g, b)"""

    font_size: float

    @property
    def color_css(self):
        if self.color is None:
            return "#000000"

        r, g, b = self.color
        return f"#{r:02x}{g:02x}{b:02x}"


class StyleArtifact(BaseModel):
    pages: list[list[BlockStyle | None]]
