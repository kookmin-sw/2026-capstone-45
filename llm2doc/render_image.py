import skia
from PIL import Image, ImageDraw


COLOR_PRIOR = "green"
COLOR_SELECTED = "blue"
COLOR_NEXT = "red"

LINE_WIDTH = 1

# CSS-like ordered font stack
FONT_FAMILIES = ["Noto Sans CJK KR", "Arial", "sans-serif"]

COLOR_TEXT_SKIA = skia.ColorBLACK
OVERFLOW_VISIBLE = False

# Access textlayout directly through the skia module
FONT_COLLECTION = skia.textlayout.FontCollection()
FONT_COLLECTION.setDefaultFontManager(skia.FontMgr())
UNICODE = skia.Unicodes.ICU.Make()


def render_single_text(image: Image.Image, bbox: list[float], text: str) -> Image.Image:
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


def render_boxes(
    image: Image.Image,
    bboxes: list[list[float]],
    texts: list[str | None] | None = None,
    selected: int | None = None,
):
    image = image.convert("RGBA")
    draw = ImageDraw.Draw(image)

    img_width, img_height = image.size

    if selected is not None:
        for i, bbox in enumerate(bboxes):
            if i < selected:
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
                [x_min, y_min, x_max, y_max], outline=color, width=LINE_WIDTH
            )

    del draw

    if texts is not None:
        if len(bboxes) < len(texts):
            raise IndexError("length of texts exceeds length of bboxes")

        for i, text in enumerate(texts):
            if text is not None:
                image = render_single_text(image, bboxes[i], text)

    return image
