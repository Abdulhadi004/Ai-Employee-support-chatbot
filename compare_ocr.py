
import cv2
from image_ocr import reader, preprocess_image, preprocess_image_v2
from image_ocr import preprocess_image_v3

image_path = "sample.jpg"

original = cv2.imread(image_path)

if original is None:
    raise FileNotFoundError("Image not found!")

# Method 1: Original
original_results = reader.readtext(original)

# Method 2: CLAHE + Denoising
processed_v1 = preprocess_image(image_path)
results_v1 = reader.readtext(processed_v1)

# Method 3: Otsu thresholding
processed_v2 = preprocess_image_v2(image_path)
results_v2 = reader.readtext(processed_v2)

processed_v3 = preprocess_image_v3(image_path)
results_v3 = reader.readtext(processed_v3)


def display_results(title, results):

    print(f"\n========== {title} ==========")

    for box, text, confidence in results:
        print(f"{text} | Confidence: {confidence:.2f}")


display_results("ORIGINAL OCR", original_results)
display_results("PREPROCESSING V1", results_v1)
display_results("PREPROCESSING V2", results_v2)
display_results("PREPROCESSING V3", results_v3)