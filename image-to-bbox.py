import cv2
import json
import colorsys
import os
import sys
import numpy as np

BBOX_COLOR_HUE_INCREMENT = 20
BBOX_INPUT_FILE = "template.jpg"
BBOX_OUTPUT_FILE = "bbox.json"

# Stored as normalized YOLO format [center_x, center_y, width, height] from 0.0 to 1.0
bboxes = []
drawing = False
nix, niy = -1.0, -1.0
img_original = None
img = None
img_display = None
zoom_level = 1.0


def get_color(index):
    """
    Returns a BGR color tuple based on the bounding box index.
    The hue is incremented by BBOX_COLOR_HUE_INCREMENT degrees per index.
    """
    hue_deg = index * BBOX_COLOR_HUE_INCREMENT
    r, g, b = colorsys.hsv_to_rgb(hue_deg / 360.0, 1.0, 1.0)
    return (int(b * 255), int(g * 255), int(r * 255))


def draw_all_bboxes(canvas):
    """Redraws all committed bounding boxes using YOLO normalized coordinates."""
    h_disp, w_disp = canvas.shape[:2]

    for i, (cx, cy, nw, nh) in enumerate(bboxes):
        color = get_color(i)

        # Convert YOLO center coordinates back to top-left for OpenCV drawing
        nx = cx - (nw / 2.0)
        ny = cy - (nh / 2.0)

        # Scale the normalized coordinates to the current display size
        x1 = int(nx * w_disp)
        y1 = int(ny * h_disp)
        x2 = int((nx + nw) * w_disp)
        y2 = int((ny + nh) * h_disp)

        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)


def update_zoom():
    """Resizes the base image according to zoom_level and updates the display."""
    global img, img_display
    h, w = img_original.shape[:2]
    new_w, new_h = int(w * zoom_level), int(h * zoom_level)

    # Resize from the pristine original to prevent quality degradation
    img = cv2.resize(img_original, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    img_display = img.copy()
    draw_all_bboxes(img_display)

    # Print current zoom state
    print(f"[INFO] Zoom level: {zoom_level}x")


def mouse_callback(event, x, y, flags, param):
    """Handles mouse events and normalizes coordinates immediately."""
    global drawing, nix, niy, img_display, img

    h_disp, w_disp = img.shape[:2]

    # Immediately convert display x,y to normalized 0.0-1.0 coordinates
    # np.clip ensures boxes don't break if you drag the mouse outside the window
    nx = np.clip(x / float(w_disp), 0.0, 1.0)
    ny = np.clip(y / float(h_disp), 0.0, 1.0)

    if event == cv2.EVENT_LBUTTONDOWN:
        drawing = True
        nix, niy = nx, ny

    elif event == cv2.EVENT_MOUSEMOVE:
        if drawing:
            img_display = img.copy()
            draw_all_bboxes(img_display)

            # Preview the current bounding box being drawn
            color = get_color(len(bboxes))
            start_x, start_y = int(nix * w_disp), int(niy * h_disp)
            cv2.rectangle(img_display, (start_x, start_y), (x, y), color, 2)

    elif event == cv2.EVENT_LBUTTONUP:
        if drawing:
            drawing = False
            # Only append if it's an actual box and not a static click
            if nx != nix and ny != niy:
                xmin = min(nix, nx)
                ymin = min(niy, ny)
                nw = abs(nx - nix)
                nh = abs(ny - niy)

                # Convert to YOLO format (center x, center y)
                cx = xmin + (nw / 2.0)
                cy = ymin + (nh / 2.0)

                bboxes.append([cx, cy, nw, nh])

            img_display = img.copy()
            draw_all_bboxes(img_display)


def save_bboxes():
    """Saves the pre-normalized bboxes directly to JSON."""
    with open(BBOX_OUTPUT_FILE, "w") as f:
        json.dump(bboxes, f, indent=4)
    print(f"\n[INFO] Saved {len(bboxes)} bounding boxes to '{BBOX_OUTPUT_FILE}'.")


def main():
    global img_original, img, img_display, zoom_level

    if not os.path.exists(BBOX_INPUT_FILE):
        print(f"[ERROR] '{BBOX_INPUT_FILE}' not found in the working directory.")
        sys.exit(1)

    img_original = cv2.imread(BBOX_INPUT_FILE)
    if img_original is None:
        print(f"[ERROR] Could not load '{BBOX_INPUT_FILE}'. Ensure it is a valid format.")
        sys.exit(1)

    img = img_original.copy()
    img_display = img.copy()

    cv2.namedWindow("Image")
    cv2.setMouseCallback("Image", mouse_callback)

    print("--- Controls ---")
    print(" Mouse: Click and drag to draw a bounding box")
    print("   '[': Zoom out (Decrease zoom by 0.1x)")
    print("   ']': Zoom in (Increase zoom by 0.1x)")
    print("   'u': Undo the last drawn bounding box")
    print("   'q': Save to JSON and quit")
    print("----------------")

    while True:
        cv2.imshow("Image", img_display)
        key = cv2.waitKey(20) & 0xFF

        if key == ord("q"):
            save_bboxes()
            break
        elif key == ord("u"):
            if len(bboxes) > 0:
                bboxes.pop()
                img_display = img.copy()
                draw_all_bboxes(img_display)
        elif key == ord("["):
            zoom_level = round(float(np.clip(zoom_level - 0.1, 0.1, 4.0)), 1)
            update_zoom()
        elif key == ord("]"):
            zoom_level = round(float(np.clip(zoom_level + 0.1, 0.1, 4.0)), 1)
            update_zoom()

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
