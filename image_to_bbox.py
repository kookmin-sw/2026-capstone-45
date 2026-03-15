import cv2
import json
import colorsys
import os
import sys
import numpy as np

# Global Constants
BBOX_COLOR_HUE_INCREMENT = 20
BBOX_INPUT_FILE = "template.jpg"
BBOX_OUTPUT_FILE = "bbox.json"

# Global State Variables
bboxes = [] # Stored in ORIGINAL image coordinates
drawing = False
ix, iy = -1, -1 # Stored in ORIGINAL image coordinates
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
    """Redraws all committed bounding boxes on the canvas, scaled to current zoom."""
    for i, (x1, y1, x2, y2) in enumerate(bboxes):
        color = get_color(i)
        # Scale the original coordinates to the current zoom level for display
        zx1, zy1 = int(x1 * zoom_level), int(y1 * zoom_level)
        zx2, zy2 = int(x2 * zoom_level), int(y2 * zoom_level)
        cv2.rectangle(canvas, (zx1, zy1), (zx2, zy2), color, 2)

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
    """Handles mouse events for drawing bounding boxes."""
    global drawing, ix, iy, img_display, img

    # Map the mouse coordinates back to the original image dimensions
    orig_x = int(x / zoom_level)
    orig_y = int(y / zoom_level)

    if event == cv2.EVENT_LBUTTONDOWN:
        drawing = True
        ix, iy = orig_x, orig_y

    elif event == cv2.EVENT_MOUSEMOVE:
        if drawing:
            img_display = img.copy()
            draw_all_bboxes(img_display)
            
            # Preview the current bounding box being drawn
            color = get_color(len(bboxes))
            zx1, zy1 = int(ix * zoom_level), int(iy * zoom_level)
            cv2.rectangle(img_display, (zx1, zy1), (x, y), color, 2)

    elif event == cv2.EVENT_LBUTTONUP:
        if drawing:
            drawing = False
            # Only append if it's an actual box
            if orig_x != ix and orig_y != iy:
                bboxes.append((ix, iy, orig_x, orig_y))
            
            img_display = img.copy()
            draw_all_bboxes(img_display)

def save_bboxes():
    """Calculates normalized top-left xywh coordinates and saves to JSON."""
    # Use the original image dimensions for accurate normalization
    h_img, w_img = img_original.shape[:2]
    normalized_bboxes = []
    
    for (x1, y1, x2, y2) in bboxes:
        xmin = min(x1, x2)
        xmax = max(x1, x2)
        ymin = min(y1, y2)
        ymax = max(y1, y2)

        nx = xmin / w_img
        ny = ymin / h_img
        nw = (xmax - xmin) / w_img
        nh = (ymax - ymin) / h_img
        
        normalized_bboxes.append([nx, ny, nw, nh])
        
    with open(BBOX_OUTPUT_FILE, 'w') as f:
        json.dump(normalized_bboxes, f, indent=4)
    print(f"\n[INFO] Saved {len(normalized_bboxes)} bounding boxes to '{BBOX_OUTPUT_FILE}'.")

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
    print("   '[': Zoom in (Increase zoom by 0.1x)")
    print("   ']': Zoom out (Decrease zoom by 0.1x)")
    print("   'u': Undo the last drawn bounding box")
    print("   'q': Save to JSON and quit")
    print("----------------")

    while True:
        cv2.imshow("Image", img_display)
        key = cv2.waitKey(20) & 0xFF
        
        if key == ord('q'):
            save_bboxes()
            break
        elif key == ord('u'):
            if len(bboxes) > 0:
                bboxes.pop()
                img_display = img.copy()
                draw_all_bboxes(img_display)
        elif key == ord('['):
            zoom_level = round(float(np.clip(zoom_level - 0.1, 0.1, 4.0)), 1)
            update_zoom()
        elif key == ord(']'):
            zoom_level = round(float(np.clip(zoom_level + 0.1, 0.1, 4.0)), 1)
            update_zoom()

    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
