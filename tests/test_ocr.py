
from image_ocr import extract_text_from_image

image_path = "sample.jpg"

print("\nReading image...\n")

text = extract_text_from_image(image_path)

print("Extracted Text:")
print("--------------------")
print(text)
