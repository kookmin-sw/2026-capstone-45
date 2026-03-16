import os
import json
import skia
from PIL import Image, ImageDraw

INPUT_IMAGE_PATH = "template.png"
OUTPUT_IMAGE_PATH = "template_rendered.png"

COLOR_PRIOR = "green"
COLOR_SELECTED = "orange"
COLOR_NEXT = "red"
COLOR_DEFAULT = "red"

LINE_WIDTH = 3

# CSS-like ordered font stack
FONT_FAMILIES = ["Noto Serif CJK KR", "Georgia", "serif"]

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
        paragraph.layout(100000.0)
        return paragraph

    # 1. Measure at an arbitrary reference size
    ref_size = 100.0
    ref_paragraph = create_paragraph(text, ref_size)
    ref_height = ref_paragraph.Height

    # 2. Mathematically exact scale factor
    scale_factor = box_height / ref_height
    final_font_size = ref_size * scale_factor

    # 3. Create the final shaped paragraph
    final_paragraph = create_paragraph(text, final_font_size)

    # 4. Setup Skia Surface
    surface = skia.Surface.MakeRasterN32Premul(box_width, box_height)
    canvas = surface.getCanvas()

    # 5. Handle Native Clipping
    if not OVERFLOW_VISIBLE:
        clip_rect = skia.Rect.MakeWH(box_width, box_height)
        canvas.clipRect(clip_rect, skia.ClipOp.kIntersect, True)

    # 6. Draw Text
    final_paragraph.paint(canvas, 0, 0)

    # 7. Convert Skia Surface back to PIL Image and paste
    snapshot = surface.makeImageSnapshot()
    image_array = snapshot.toarray(
        colorType=skia.ColorType.kRGBA_8888_ColorType,
        alphaType=skia.AlphaType.kUnpremul_AlphaType,
    )

    text_overlay = Image.fromarray(image_array, "RGBA")
    image.paste(text_overlay, (int(x_min), int(y_min)), mask=text_overlay)

    return image

def render_image(bboxes: list[list[float]], selected: int | None) -> Image.Image:
    if not os.path.exists(INPUT_IMAGE_PATH):
        print(f"Error: The input image '{INPUT_IMAGE_PATH}' does not exist.")
        raise FileNotFoundError(f"Input image not found: {INPUT_IMAGE_PATH}")

    img = Image.open(INPUT_IMAGE_PATH).convert("RGBA")
        
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
    with open("bbox.json", "rb") as f:
        bboxes = json.load(f)

    selected_index = 2

    # Render the image borders
    result_image = render_image(bboxes, selected_index)

    # Example: Render text into the selected bounding box
    if len(bboxes) > selected_index:
        sample_text = "좋아요\n✅"
        result_image = render_text(result_image, bboxes[selected_index], sample_text)

    # Save the result
    result_image.save(OUTPUT_IMAGE_PATH)
    print(f"Image successfully rendered and saved to {OUTPUT_IMAGE_PATH}")


if __name__ == "__main__":
    main()
