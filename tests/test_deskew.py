
import cv2
import matplotlib.pyplot as plt

from image_ocr import correct_orientation, deskew_image

image_path = "sample.jpg"

image = cv2.imread(image_path)

if image is None:
    raise FileNotFoundError("Image not found!")

corrected = deskew_image(image)

original_rgb = cv2.cvtColor(
    image,
    cv2.COLOR_BGR2RGB
)

corrected_rgb = cv2.cvtColor(
    corrected,
    cv2.COLOR_BGR2RGB
)

plt.figure(figsize=(12, 6))

plt.subplot(1, 2, 1)
plt.imshow(original_rgb)
plt.title("Original")
plt.axis("off")

plt.subplot(1, 2, 2)
plt.imshow(corrected_rgb)
plt.title("Deskewed")
plt.axis("off")

plt.tight_layout()
plt.show()
