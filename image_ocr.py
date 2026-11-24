
from pathlib import Path
import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR


print("Loading OCR model...")

reader = None
rapid_reader = RapidOCR()

print("OCR model loaded successfully!")


def _get_easyocr_reader():
    global reader
    if reader is None:
        import easyocr

        reader = easyocr.Reader(
            ['en', 'ur'],
            gpu=False
        )
    return reader

def preprocess_image(image_path: str):

    # Read image
    image = cv2.imread(str(image_path))

    if image is None:
        raise ValueError("Could not read the image.")

    # 1. Resize image to improve small text recognition
    height, width = image.shape[:2]

    if height < 1200:
        scale = 1200 / height
        new_width = int(width * scale)
        image = cv2.resize(
            image,
            (new_width, 1200),
            interpolation=cv2.INTER_CUBIC
        )

    # 2. Convert to grayscale
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # 3. Improve contrast using CLAHE
    clahe = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(8, 8)
    )

    enhanced = clahe.apply(gray)

    # 4. Reduce noise while preserving text edges
    denoised = cv2.bilateralFilter(
        enhanced,
        9,
        75,
        75
    )

    return denoised


def preprocess_image_v2(image_path: str):

    image = cv2.imread(str(image_path))

    if image is None:
        raise ValueError("Could not read image.")

    # Convert to grayscale
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Upscale image
    height, width = gray.shape

    if height < 1200:
        scale = 1200 / height

        gray = cv2.resize(
            gray,
            (int(width * scale), 1200),
            interpolation=cv2.INTER_CUBIC
        )

    # Apply Otsu thresholding
    _, thresholded = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )

    return thresholded


def preprocess_image_v3(image_path: str):

    image = cv2.imread(str(image_path))

    if image is None:
        raise ValueError("Could not read image.")

    # Convert to grayscale
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Upscale small images
    height, width = gray.shape

    if height < 1200:
        scale = 1200 / height

        gray = cv2.resize(
            gray,
            (int(width * scale), 1200),
            interpolation=cv2.INTER_CUBIC
        )

    # Adaptive thresholding
    adaptive = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        10
    )

    return adaptive


def compare_ocr_methods(image_path: str):

    image = cv2.imread(str(image_path))

    if image is None:
        raise FileNotFoundError("Image not found!")

    # Apply gentle preprocessing
    processed = preprocess_image(str(image_path))

    # Pass 1: Default EasyOCR
    original_results = _get_easyocr_reader().readtext(
        image,
        detail=1,
        paragraph=False
    )

    # Pass 2: Beam search
    improved_results = _get_easyocr_reader().readtext(
        processed,
        decoder="beamsearch",
        beamWidth=5,
        detail=1,
        paragraph=False,
        contrast_ths=0.1,
        adjust_contrast=0.5
    )

    def print_results(title, results):

        print(f"\n========== {title} ==========")

        for box, text, confidence in results:

            print(
                f"Text: {text} | "
                f"Confidence: {confidence:.3f}"
            )

    print_results("DEFAULT OCR", original_results)

    print_results("BEAM SEARCH OCR", improved_results)


def extract_text_with_best_method(image_path: str):

    image = cv2.imread(str(image_path))

    if image is None:
        raise ValueError("Could not read image.")

    # Prepare different image versions
    original = image
    enhanced = preprocess_image(str(image_path))

    methods = {
        "Original": original,
        "CLAHE": enhanced
    }

    best_result = None
    best_score = -1
    best_method = None

    for method_name, processed_image in methods.items():

        results = _get_easyocr_reader().readtext(processed_image)

        if not results:
            continue

        # Calculate average OCR confidence
        average_confidence = sum(
            result[2] for result in results
        ) / len(results)

        print(f"\n{method_name} confidence: {average_confidence:.2f}")

        if average_confidence > best_score:

            best_score = average_confidence
            best_result = results
            best_method = method_name

    if best_result is None:
        return ""

    print(f"\nSelected method: {best_method}")

    extracted_text = [
        text for box, text, confidence in best_result
    ]

    return "\n".join(extracted_text)




def deskew_image(image):

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Detect dark text pixels
    _, binary = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )

    # Find foreground coordinates
    coordinates = np.column_stack(
        np.where(binary > 0)
    )

    if len(coordinates) < 10:
        return image

    # Detect rotation angle
    angle = cv2.minAreaRect(coordinates)[-1]

    # Normalize angle
    if angle < -45:
        angle = 90 + angle

    print("Detected angle:", angle)

    # Do not apply large rotations here
    if abs(angle) > 15:
        print("Large rotation detected. Skipping deskew.")
        return image

    # Rotate in the opposite direction
    height, width = image.shape[:2]

    center = (width // 2, height // 2)

    matrix = cv2.getRotationMatrix2D(
        center,
        angle,
        1.0
    )

    corrected = cv2.warpAffine(
        image,
        matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE
    )

    return corrected



def correct_orientation(image, rotation):

    if rotation == 90:
        return cv2.rotate(
            image,
            cv2.ROTATE_90_CLOCKWISE
        )

    elif rotation == 180:
        return cv2.rotate(
            image,
            cv2.ROTATE_180
        )

    elif rotation == 270:
        return cv2.rotate(
            image,
            cv2.ROTATE_90_COUNTERCLOCKWISE
        )

    return image


def extract_detailed_text(image_path: str):

    image = cv2.imread(str(image_path))

    if image is None:
        raise FileNotFoundError("Image not found!")

    # Apply deskewing for small rotations
    corrected = deskew_image(image)

    # Run original EasyOCR settings
    results = _get_easyocr_reader().readtext(
        corrected,
        detail=1,
        paragraph=False,
        decoder="greedy"
    )

    extracted_data = []

    for box, text, confidence in results:

        extracted_data.append({
            "text": text,
            "confidence": round(float(confidence), 3),
            "bounding_box": [
                [int(point[0]), int(point[1])]
                for point in box
            ]
        })

    return extracted_data


def _box_bounds(box):
    points = np.asarray(box, dtype=float)
    return (
        float(points[:, 0].min()),
        float(points[:, 1].min()),
        float(points[:, 0].max()),
        float(points[:, 1].max())
    )


def _same_detection(first_box, second_box, same_text):
    first_left, first_top, first_right, first_bottom = _box_bounds(first_box)
    second_left, second_top, second_right, second_bottom = _box_bounds(second_box)

    intersection_width = max(
        0.0,
        min(first_right, second_right) - max(first_left, second_left)
    )
    intersection_height = max(
        0.0,
        min(first_bottom, second_bottom) - max(first_top, second_top)
    )
    intersection = intersection_width * intersection_height

    first_area = max(0.0, first_right - first_left) * max(
        0.0, first_bottom - first_top
    )
    second_area = max(0.0, second_right - second_left) * max(
        0.0, second_bottom - second_top
    )
    union = first_area + second_area - intersection

    if union > 0 and intersection / union >= 0.5:
        return True

    smaller_area = min(first_area, second_area)
    return (
        same_text
        and smaller_area > 0
        and intersection / smaller_area >= 0.8
    )


def _merge_ocr_results(results_by_variant):
    groups = []

    for variant_index, results in enumerate(results_by_variant):
        for box, text, confidence in results:
            normalized_text = " ".join(text.split()).casefold()
            matching_group = None

            for group in groups:
                representative = group[0]
                same_text = (
                    normalized_text
                    == " ".join(representative[2].split()).casefold()
                )
                if _same_detection(box, representative[1], same_text):
                    matching_group = group
                    break

            detection = (variant_index, box, text, float(confidence))
            if matching_group is None:
                groups.append([detection])
            else:
                matching_group.append(detection)

    merged = []
    for group in groups:
        text_candidates = {}
        for variant_index, box, text, confidence in group:
            normalized_text = " ".join(text.split()).casefold()
            candidate = text_candidates.setdefault(
                normalized_text,
                {"text": text, "detections": {}}
            )
            candidate["detections"][variant_index] = (
                box,
                text,
                confidence
            )

        best_candidate = max(
            text_candidates.values(),
            key=lambda candidate: (
                len(candidate["detections"]),
                sum(
                    item[2]
                    for item in candidate["detections"].values()
                ) / len(candidate["detections"])
            )
        )
        best_detection = max(
            best_candidate["detections"].values(),
            key=lambda item: item[2]
        )
        merged.append((best_detection[0], best_candidate["text"]))

    merged.sort(
        key=lambda result: (
            _box_bounds(result[0])[1],
            _box_bounds(result[0])[0]
        )
    )
    return merged


def _read_ocr_results(image):
    return _get_easyocr_reader().readtext(
        image,
        decoder="greedy",
        detail=1,
        paragraph=False,
        contrast_ths=0.1,
        adjust_contrast=0.5,
        text_threshold=0.7,
        low_text=0.4,
        link_threshold=0.4
    )


def _read_rapid_ocr_results(image):
    results, _ = rapid_reader(image)
    return results or []


def _needs_easyocr_fallback(results):
    if not results:
        return True
    average_confidence = sum(float(result[2]) for result in results) / len(results)
    return average_confidence < 0.4


def _format_ocr_results(results):
    detections = []
    for box, text in results:
        left, top, right, bottom = _box_bounds(box)
        detections.append((
            left,
            (top + bottom) / 2,
            max(1.0, bottom - top),
            right,
            text
        ))

    rows = []
    for detection in sorted(detections, key=lambda item: (item[1], item[0])):
        _, center_y, height, _, _ = detection
        matching_rows = []
        for row in rows:
            row_center = float(np.median([item[1] for item in row]))
            row_height = float(np.median([item[2] for item in row]))
            distance = abs(center_y - row_center)
            if distance <= 0.5 * max(height, row_height):
                matching_rows.append((distance, row))

        if matching_rows:
            min(matching_rows, key=lambda item: item[0])[1].append(detection)
        else:
            rows.append([detection])

    rows.sort(key=lambda row: float(np.median([item[1] for item in row])))
    header_index = None
    for index, row in enumerate(rows):
        row_text = " ".join(item[4] for item in row).casefold()
        if (
            "subject" in row_text
            and "letter grade" in row_text
            and "grade" in row_text
            and ("gpa" in row_text or "cgpa" in row_text)
        ):
            header_index = index
            break

    formatted_rows = []
    for index, row in enumerate(rows):
        row = sorted(row, key=lambda detection: detection[0])
        if header_index is not None and index >= header_index:
            if index == header_index:
                formatted_rows.append(" | ".join(item[4] for item in row))
                column_bounds = []
                for left_header, right_header in zip(row, row[1:]):
                    left_center = (left_header[0] + left_header[3]) / 2
                    right_center = (right_header[0] + right_header[3]) / 2
                    boundary = (left_header[3] + right_header[0]) / 2
                    if not left_center <= boundary <= right_center:
                        boundary = (left_center + right_center) / 2
                    column_bounds.append(boundary)
                continue

            cells = [""] * (len(column_bounds) + 1)
            for detection in row:
                center_x = (detection[0] + detection[3]) / 2
                column_index = sum(
                    center_x > boundary
                    for boundary in column_bounds
                )
                cells[column_index] = " ".join(
                    filter(None, (cells[column_index], detection[4]))
                )
            formatted_rows.append(" | ".join(cells))
        else:
            formatted_rows.append(" ".join(item[4] for item in row))

    return "\n".join(formatted_rows)


def extract_text_from_image(image_path: str) -> str:
    image_path = Path(image_path)

    if not image_path.exists():
        raise FileNotFoundError("Image file not found.")

    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError("Could not read the image.")

    primary_results = _read_rapid_ocr_results(image)
    results_by_variant = [primary_results]

    if _needs_easyocr_fallback(primary_results):
        fallback_results = _read_ocr_results(image)
        if fallback_results:
            results_by_variant.append(fallback_results)

    merged_results = _merge_ocr_results(results_by_variant)
    return _format_ocr_results(merged_results)

