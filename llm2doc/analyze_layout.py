import numpy as np

from PIL import Image, ImageDraw


def analyze_layout(img: Image.Image):
    from paddleocr import LayoutDetection

    img_arr = np.asarray(img.convert("RGB"))[..., ::-1].copy()

    # Use PP-DocLayoutV2 to get reading order
    model = LayoutDetection(
        model_name="PP-DocLayout_plus-L",
        layout_nms=True,
        threshold=0.5,
        layout_merge_bboxes_mode="large",
    )

    output = model.predict(img_arr)

    for res in output:
        res.print()
        res.save_to_img(save_path="./debug")


if __name__ == "__main__":
    img = Image.open("data/financial/original.png")
    analyze_layout(img)
