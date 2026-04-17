import io
import uuid
import base64
import numpy as np

from PIL import Image
from typing import Sequence
from pydantic import BaseModel
from beartype import beartype

from .analyze_layout import ParsedPage
from .font import PathToFontFamily


class RenderedBlock(BaseModel):
    id: str
    bbox: Sequence[float]

    line_height: float
    font_family: str
    font_size: float
    color: str

    html: str


class RenderedPage(BaseModel):
    bg_url: str
    width: int
    height: int
    blocks: list[RenderedBlock]


class RenderedDocument(BaseModel):
    id: str
    pages: list[RenderedPage]


@beartype
def _erase_bounding_box(image: Image.Image, bbox: list) -> Image.Image:
    """
    Erases an axis-aligned bounding box from a Pillow Image by filling it
    with the median color of the surrounding neighborhood.

    Args:
        image: Original PIL Image.
        bbox: List or tuple of [xmin, ymin, xmax, ymax].

    Returns:
        A new PIL Image with the bounding box erased.
    """
    MIN_PIXEL_DIM = 4  # Minimum total gap between large and small boxes
    PIXEL_DIM_RATIO = 0.1  # Ratio of box dimensions to expand/shrink

    if image.mode == "RGB":
        rgb_image = image
    else:
        rgb_image = image.convert("RGB")

    img_arr = np.array(rgb_image)
    img_height, img_width = img_arr.shape[:2]

    xmin, ymin, xmax, ymax = bbox

    box_w = xmax - xmin
    box_h = ymax - ymin

    adj_x = max(int(MIN_PIXEL_DIM / 2.0), int(box_w * PIXEL_DIM_RATIO))
    adj_y = max(int(MIN_PIXEL_DIM / 2.0), int(box_h * PIXEL_DIM_RATIO))

    l_xmin = max(0, xmin - adj_x)
    l_ymin = max(0, ymin - adj_y)
    l_xmax = min(img_width, xmax + adj_x)
    l_ymax = min(img_height, ymax + adj_y)

    s_xmin = min(xmin + box_w // 2, xmin + adj_x)
    s_ymin = min(ymin + box_h // 2, ymin + adj_y)
    s_xmax = max(xmin + box_w // 2, xmax - adj_x)
    s_ymax = max(ymin + box_h // 2, ymax - adj_y)

    mask = np.zeros((img_height, img_width), dtype=np.uint8)

    mask[l_ymin:l_ymax, l_xmin:l_xmax] = 255
    mask[s_ymin:s_ymax, s_xmin:s_xmax] = 0

    border_pixels = img_arr[mask == 255]

    if len(border_pixels) > 0:
        median_color = np.median(border_pixels, axis=0).astype(np.uint8)

        img_arr[ymin - 2 : ymax + 3, xmin - 2 : xmax + 3] = median_color

    return Image.fromarray(img_arr)


@beartype
def _extend_bounding_box(image: Image.Image, bbox: Sequence[int | float]) -> list[int | float]:
    """
    Extends the bounding box to the right as long as the right border pattern repeats.
    Checks a 4-pixel lookahead window to ensure the column pattern is stable.
    Terminates if any pixel in the lookahead differs from the original right-most column,
    or if it reaches page_margin pixels from the right edge of the image.

    Args:
        image: Original PIL Image.
        bbox: Sequence of [xmin, ymin, xmax, ymax].

    Returns:
        A new bounding box list with the extended xmax.
    """

    PAGE_MARGIN = 8

    xmin, ymin, xmax, ymax = [int(v) for v in bbox]

    rgb_image = image.convert("RGB")
    img_arr = np.array(rgb_image)
    img_height, img_width = img_arr.shape[:2]

    # Handle edge cases (invalid bounds, negative sizes)
    if xmax <= 0 or xmax > img_width or ymin < 0 or ymax > img_height or ymin >= ymax:
        return list(bbox)

    right_border_x = xmax - 1
    reference_column = img_arr[ymin:ymax, right_border_x:xmax]

    new_xmax = xmax
    max_limit_x = img_width - PAGE_MARGIN

    for x in range(xmax, max_limit_x):
        current_border = img_arr[ymin:ymax, x : x + 4]

        if np.all(current_border == reference_column):
            new_xmax = x + 1
        else:
            break

    return [bbox[0], bbox[1], type(bbox[2])(new_xmax), bbox[3]]


@beartype
def render_page(page: ParsedPage, img: Image.Image, htmls: Sequence[str | None], page_id: str) -> RenderedPage:
    font_mapper = PathToFontFamily()
    blocks: list[RenderedBlock] = []

    img = img.convert("RGB")

    assert len(page.blocks) == len(htmls)

    for i, (block, html) in enumerate(zip(page.blocks, htmls)):
        if html is None:
            continue

        bbox = block.bbox
        can_extend = False

        line_height = bbox[3] - bbox[1]
        font_family = "sans-serif"
        font_size = line_height
        color = "#000"

        if block.style is not None:
            # TODO: line_height왜 이렇게 들어가는지 확인
            line_height = (block.bbox[3] - block.bbox[1]) / block.style.line_count
            font_family = font_mapper.path_to_font(block.style.font_family)
            font_size = block.style.font_size
            color = block.style.color_css

            can_extend = block.style.line_count == 1 or block.content.strip().count("\n") + 1 == block.style.line_count

        if can_extend:
            bbox = _extend_bounding_box(img, bbox)

        img = _erase_bounding_box(img, bbox)

        blocks.append(
            RenderedBlock(
                id=f"{page_id}-block-{i}",
                bbox=[float(x) for x in bbox],
                line_height=line_height,
                font_family=font_family,
                font_size=font_size,
                color=color,
                html=html,
            )
        )

    buf = io.BytesIO()
    img.save(buf, "png")

    bg_url = "data:image/png;base64," + base64.standard_b64encode(buf.getvalue()).decode("ascii")

    return RenderedPage(
        bg_url=bg_url,
        width=img.width,
        height=img.height,
        blocks=blocks,
    )


@beartype
def render_document(pages: list[RenderedPage]) -> RenderedDocument:
    return RenderedDocument(
        id=uuid.uuid4().hex,
        pages=pages,
    )
