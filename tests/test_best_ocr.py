
from image_ocr import extract_text_with_best_method

image_path = "sample.jpg"

print("\n========== AUTOMATIC OCR ==========")

text = extract_text_with_best_method(image_path)

print("\n========== FINAL EXTRACTED TEXT ==========")
print(text)
