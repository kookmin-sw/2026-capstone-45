import numpy as np
import os

from PIL import Image, ImageDraw

from paddleocr import LayoutDetection

# Use PP-DocLayoutV2 to get reading order
model = LayoutDetection(
    model_name="PP-DocLayoutV2",
    layout_nms=True,
    threshold=0.5,
    layout_merge_bboxes_mode="large",
)

def analyze_layout(img: Image.Image, save_path: str):

    img_arr = np.asarray(img.convert("RGB"))[..., ::-1].copy()

    output = model.predict(img_arr)

    for res in output:
        res.save_to_img(save_path=save_path)


def main():
    os.makedirs("paddle", exist_ok=True)

    for file_name in os.listdir("images"):
        print(f"Processing {file_name}...", flush=True)
        img = Image.open(f"images/{file_name}")
        analyze_layout(img, f"./paddle/{file_name}")


if __name__ == "__main__":
    main()
