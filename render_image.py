import os
import json
from PIL import Image, ImageDraw


INPUT_IMAGE_PATH = "template.jpg"
OUTPUT_IMAGE_PATH = "template_rendered.png"

COLOR_PRIOR = "green"
COLOR_SELECTED = "orange"
COLOR_NEXT = "red"
COLOR_DEFAULT = "red"

LINE_WIDTH = 3


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
    
    selected_index = 1
    
    # Render the image
    result_image = render_image(bboxes, selected_index)
    
    # Save the result
    result_image.save(OUTPUT_IMAGE_PATH)
    print(f"Image successfully rendered and saved to {OUTPUT_IMAGE_PATH}")


if __name__ == "__main__":
    main()
