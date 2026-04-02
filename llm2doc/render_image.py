import os
import math
import uuid
import tempfile
import numpy as np
from PIL import Image, ImageDraw
from beartype import beartype
from typing import Sequence
from html2image import Html2Image


COLOR_PRIOR = "green"
COLOR_SELECTED = "blue"
COLOR_NEXT = "red"

LINE_WIDTH = 2


def _create_html2image_instance():
    tempdir = tempfile.gettempdir()

    try:
        return Html2Image(browser="chrome", output_path=tempdir)
    except FileNotFoundError:
        pass

    try:
        return Html2Image(browser="edge", output_path=tempdir)
    except FileNotFoundError:
        pass

    raise RuntimeError("Could not find a suitable browser.")


hti = _create_html2image_instance()


@beartype
def _render_single_html(
    image: Image.Image, bbox: Sequence[int | float], html: str
) -> Image.Image:
    bbox = _extend_bounding_box(image, bbox)
    x_min, y_min, x_max, y_max = bbox

    box_width = int(x_max - x_min)
    box_height = int(y_max - y_min)

    if box_width <= 0 or box_height <= 0:
        return image

    image = image.convert("RGB")

    img_arr = np.array(image)
    bg_color = np.median(img_arr[y_min:y_max, x_min:x_max], axis=(0, 1))
    bg_color = "".join([f"{int(x):02x}" for x in bg_color])

    styled_html = f"""
    <html>
    <head>
        <style>
            body {{
                overflow: hidden;
                background-color: #{bg_color};
                width: {box_width}px;
                height: {box_height}px;
                min-width: {box_width}px;
                min-height: {box_height}px;
                max-width: {box_width}px;
                max-height: {box_height}px;
            }}
            *, ::after, ::before {{
                box-sizing: border-box;
                margin: 0;
                padding: 0;
            }}
        </style>
    </head>
    <body>
        {html}
    </body>
    </html>
    """

    temp_filename = f"temp_render_{uuid.uuid4().hex}.png"

    final_filename = hti.screenshot(
        html_str=styled_html, save_as=temp_filename, size=(box_width, box_height)
    )[0]

    try:
        html_image = Image.open(final_filename).convert("RGBA")

        image.paste(html_image, (int(x_min), int(y_min)), mask=html_image)
    finally:
        if os.path.exists(final_filename):
            os.remove(final_filename)

    return image


@beartype
def _draw_striped_rectangle(
    draw: ImageDraw.ImageDraw,
    bbox: Sequence[int | float],
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
def _extend_bounding_box(
    image: Image.Image, bbox: Sequence[int | float]
) -> list[int | float]:
    """
    Extends the bounding box to the right as long as the right border is a uniform color.
    Terminates if any pixel on the right border differs in color (even before extending),
    or if it reaches page_margin pixels from the right edge of the image.

    Args:
        image: Original PIL Image.
        bbox: Sequence of [xmin, ymin, xmax, ymax].
        page_margin: Pixels to keep from the right end of the image.

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
    initial_border = img_arr[ymin:ymax, right_border_x]

    reference_color = initial_border[0]
    if not np.all(initial_border == reference_color):
        return list(bbox)

    new_xmax = xmax
    max_limit_x = img_width - PAGE_MARGIN

    for x in range(xmax, max_limit_x):
        current_border = img_arr[ymin:ymax, x]

        if np.all(current_border == reference_color):
            new_xmax = x + 1
        else:
            break

    return [bbox[0], bbox[1], type(bbox[2])(new_xmax), bbox[3]]


@beartype
def render_boxes(
    image: Image.Image,
    bboxes: Sequence[Sequence[int | float]],
    html: Sequence[str | None] | None = None,
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

            _draw_striped_rectangle(
                draw=draw,
                bbox=bbox,
                colors=stripe_pattern,
                width=LINE_WIDTH,
                dash_length=15,
            )

    del draw

    if html is not None:
        if len(bboxes) < len(html):
            raise IndexError("length of html_fragments exceeds length of bboxes")

        for i, html_frag in enumerate(html):
            if html_frag is not None:
                image = _render_single_html(image, bboxes[i], html_frag)

    return image
