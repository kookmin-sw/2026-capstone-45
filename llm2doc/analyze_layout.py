from PIL import Image
from surya.foundation import FoundationPredictor
from surya.recognition import RecognitionPredictor
from surya.detection import DetectionPredictor


def analyze_layout(img: Image.Image):
    img = img.convert("RGB")
    foundation_predictor = FoundationPredictor()
    recognition_predictor = RecognitionPredictor(foundation_predictor)
    detection_predictor = DetectionPredictor()

    predictions = recognition_predictor([img], det_predictor=detection_predictor)

    print(predictions)


if __name__ == "__main__":
    img = Image.open("data/financial/original.png")
    analyze_layout(img)
