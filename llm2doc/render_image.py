import math
import numpy as np
import skia
from PIL import Image, ImageDraw
from beartype import beartype


COLOR_PRIOR = "green"
COLOR_SELECTED = "blue"
COLOR_NEXT = "red"

LINE_WIDTH = 2

# CSS-like ordered font stack
FONT_FAMILIES = ["Noto Sans CJK KR", "Arial", "sans-serif"]

COLOR_TEXT_SKIA = skia.ColorBLACK
OVERFLOW_VISIBLE = False

# Access textlayout directly through the skia module
FONT_COLLECTION = skia.textlayout.FontCollection()
FONT_COLLECTION.setDefaultFontManager(skia.FontMgr())
UNICODE = skia.Unicodes.ICU.Make()


@beartype
def render_single_text(
    image: Image.Image, bbox: list[int | float], text: str
) -> Image.Image:
    # Unpack absolute coordinates
    x_min, y_min, x_max, y_max = bbox

    abs_width = x_max - x_min
    abs_height = y_max - y_min

    box_width = int(abs_width)
    box_height = int(abs_height)

    def create_paragraph(
        text_content: str, font_size: float
    ) -> skia.textlayout.Paragraph:
        para_style = skia.textlayout.ParagraphStyle()
        text_style = skia.textlayout.TextStyle()
        text_style.setColor(COLOR_TEXT_SKIA)
        text_style.setFontSize(font_size)
        text_style.setFontFamilies(FONT_FAMILIES)

        builder = skia.textlayout.ParagraphBuilder(para_style, FONT_COLLECTION, UNICODE)
        builder.pushStyle(text_style)
        builder.addText(text_content)

        paragraph = builder.Build()
        return paragraph

    min_size = 1.0
    max_size = float(max(box_width, box_height))
    best_size = min_size
    final_paragraph = None

    # Binary search for optimal text size
    for _ in range(100):
        mid_size = (min_size + max_size) / 2
        para = create_paragraph(text, mid_size)

        para.layout(box_width)

        if para.Height <= box_height and para.MinIntrinsicWidth <= box_width:
            best_size = mid_size
            min_size = mid_size
            final_paragraph = para
        else:
            max_size = mid_size

    if final_paragraph is None:
        final_paragraph = create_paragraph(text, best_size)
        final_paragraph.layout(box_width)

    surface = skia.Surface.MakeRasterN32Premul(box_width, box_height)
    canvas = surface.getCanvas()

    if not OVERFLOW_VISIBLE:
        clip_rect = skia.Rect.MakeWH(box_width, box_height)
        canvas.clipRect(clip_rect, skia.ClipOp.kIntersect, True)

    final_paragraph.paint(canvas, 0, 0)

    snapshot = surface.makeImageSnapshot()
    image_array = snapshot.toarray(
        colorType=skia.ColorType.kRGBA_8888_ColorType,
        alphaType=skia.AlphaType.kUnpremul_AlphaType,
    )

    text_overlay = Image.fromarray(image_array, "RGBA")
    image.paste(text_overlay, (int(x_min), int(y_min)), mask=text_overlay)

    return image


@beartype
def draw_striped_rectangle(
    draw: ImageDraw.ImageDraw,
    bbox: list[int | float],
    colors: list,
    width: int,
    dash_length: int,
):
    """Helper function to draw a dashed/striped rectangle."""
    x_min, y_min, x_max, y_max = bbox

    # Define the 4 line segments of the rectangle's perimeter
    lines = [
        ((x_min, y_min), (x_max, y_min)),  # Top
        ((x_max, y_min), (x_max, y_max)),  # Right
        ((x_max, y_max), (x_min, y_max)),  # Bottom
        ((x_min, y_max), (x_min, y_min)),  # Left
    ]

    color_idx = 0

    for start_pt, end_pt in lines:
        x1, y1 = start_pt
        x2, y2 = end_pt

        # Total distance of the current edge
        length = math.hypot(x2 - x1, y2 - y1)
        if length == 0:
            continue

        dx = (x2 - x1) / length
        dy = (y2 - y1) / length

        # Step along the edge and draw dashes
        curr_dist = 0
        while curr_dist < length:
            dash_end = min(curr_dist + dash_length, length)

            px1 = x1 + dx * curr_dist
            py1 = y1 + dy * curr_dist
            px2 = x1 + dx * dash_end
            py2 = y1 + dy * dash_end

            # Select the next color in the pattern
            current_color = colors[color_idx % len(colors)]
            draw.line([(px1, py1), (px2, py2)], fill=current_color, width=width)

            curr_dist += dash_length
            color_idx += 1


@beartype
def erase_bounding_box(image: Image.Image, bbox: list) -> Image.Image:
    """
    Erases an axis-aligned bounding box from a Pillow Image by filling it
    with the median color of the surrounding neighborhood.

    Args:
        image: Original PIL Image.
        bbox: List or tuple of [xmin, ymin, xmax, ymax].

    Returns:
        A new PIL Image with the bounding box erased.
    """
    MIN_PIXEL_DIM = 10  # Minimum total gap between large and small boxes
    PIXEL_DIM_RATIO = 0.10  # Ratio of box dimensions to expand/shrink

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

        img_arr[ymin:ymax, xmin:xmax] = median_color

    return Image.fromarray(img_arr)


@beartype
def render_boxes(
    image: Image.Image,
    bboxes: list[list[int | float]],
    texts: list[str | None] | None = None,
    selected: int | None = None,
):
    image = image.convert("RGBA")
    draw = ImageDraw.Draw(image)

    if selected is not None:
        for i, bbox in enumerate(bboxes):
            if i < selected:
                base_color = COLOR_PRIOR
            elif i == selected:
                base_color = COLOR_SELECTED
            else:
                base_color = COLOR_NEXT

            # Define the repeating stripe pattern.
            # E.g., White -> Target Color -> Black -> Target Color
            stripe_pattern = ["white", base_color, "black", base_color]

            draw_striped_rectangle(
                draw=draw,
                bbox=bbox,
                colors=stripe_pattern,
                width=LINE_WIDTH,
                dash_length=15,
            )

    del draw

    if texts is not None:
        if len(bboxes) < len(texts):
            raise IndexError("length of texts exceeds length of bboxes")

        for i, text in enumerate(texts):
            if text is not None:
                image = render_single_text(image, bboxes[i], text)

    return image
