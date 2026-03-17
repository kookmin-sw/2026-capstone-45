import argparse
import os
import json
import skia
from PIL import Image, ImageDraw

DEFAULT_INPUT_IMAGE_PATH = "data/financial/erased.png"
DEFAULT_OUTPUT_IMAGE_PATH = "rendered.png"
DEFAULT_TEXT = "Rendering test\n렌더링 테스트\n✅"

COLOR_PRIOR = "green"
COLOR_SELECTED = "blue"
COLOR_NEXT = "red"
COLOR_DEFAULT = "red"

LINE_WIDTH = 1

# CSS-like ordered font stack
FONT_FAMILIES = ["Noto Sans CJK KR", "Arial", "sans-serif"]

# Use the hex equivalent of skia.ColorBLACK to prevent IDE unresolved warnings
COLOR_TEXT_SKIA = skia.ColorBLACK
OVERFLOW_VISIBLE = False

# Access textlayout directly through the skia module
FONT_COLLECTION = skia.textlayout.FontCollection()
FONT_COLLECTION.setDefaultFontManager(skia.FontMgr())
UNICODE = skia.Unicodes.ICU.Make()


def render_text(image: Image.Image, bbox: list[float], text: str) -> Image.Image:
    img_width, img_height = image.size
    x_center, y_center, width, height = bbox

    abs_width = width * img_width
    abs_height = height * img_height
    x_min = (x_center * img_width) - (abs_width / 2)
    y_min = (y_center * img_height) - (abs_height / 2)

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


def render_image(
    bboxes: list[list[float]], selected: int | None, input_image: Image.Image
) -> Image.Image:
    img = input_image.convert("RGBA")
        
    draw = ImageDraw.Draw(img)
    img_width, img_height = img.size

    for i, bbox in enumerate(bboxes):
        if selected is None:
            color = COLOR_DEFAULT
        elif i < selected:
            color = COLOR_PRIOR
        elif i == selected:
            color = COLOR_SELECTED
        else:
            color = COLOR_NEXT

        x_center, y_center, width, height = bbox

        abs_x_center = x_center * img_width
        abs_y_center = y_center * img_height
        abs_width = width * img_width
        abs_height = height * img_height

        x_min = abs_x_center - (abs_width / 2)
        y_min = abs_y_center - (abs_height / 2)
        x_max = abs_x_center + (abs_width / 2)
        y_max = abs_y_center + (abs_height / 2)

        draw.rectangle(
            [x_min, y_min, x_max, y_max],
            outline=color,
            width=LINE_WIDTH
        )

    return img


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", default=DEFAULT_INPUT_IMAGE_PATH)
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT_IMAGE_PATH)
    parser.add_argument("-t", "--text", default=DEFAULT_TEXT)
    parser.add_argument("-n", "--nth-bbox", type=int, default=None)

    args = parser.parse_args()

    if args.text == DEFAULT_TEXT and args.nth_bbox is None:
        args.nth_bbox = 1
    if args.text and args.nth_bbox is None:
        parser.error("-n/--nth-bbox must be provided if text is provided.")

    with open("bbox.json", "rb") as f:
        bboxes = json.load(f)

    if not os.path.exists(args.input):
        print(f"Error: The input image '{args.input}' does not exist.")
        raise FileNotFoundError(f"Input image not found: {args.input}")

    base_image = Image.open(args.input)

    result_image = render_image(bboxes, args.nth_bbox, base_image)

    if args.text and args.nth_bbox is not None and len(bboxes) > args.nth_bbox:
        result_image = render_text(result_image, bboxes[args.nth_bbox], args.text)

    result_image.save(args.output)
    print(f"Image successfully rendered and saved to {args.output}")


if __name__ == "__main__":
    main()
