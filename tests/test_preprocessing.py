
import cv2
import matplotlib.pyplot as plt

from image_ocr import preprocess_image

image_path = "sample.jpg"

# Read original image
original = cv2.imread(image_path)

if original is None:
    raise FileNotFoundError("Image not found!")

# Convert original image from BGR to RGB
original_rgb = cv2.cvtColor(original, cv2.COLOR_BGR2RGB)

# Preprocess image
processed_image = preprocess_image(image_path)

# Display both images
plt.figure(figsize=(14, 7))

plt.subplot(1, 2, 1)
plt.imshow(original_rgb)
plt.title("Original Image")
plt.axis("off")

plt.subplot(1, 2, 2)
plt.imshow(processed_image, cmap="gray")
plt.title("Preprocessed Image")
plt.axis("off")

plt.tight_layout()
plt.show()
