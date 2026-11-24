import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from image_ocr import (
    _format_ocr_results,
    _merge_ocr_results,
    extract_text_from_image
)


def text_box(left, top, right, bottom):
    return [
        [left, top],
        [right, top],
        [right, bottom],
        [left, bottom]
    ]


class OCRMergeTests(unittest.TestCase):
    def test_format_ocr_results_keeps_table_cells_on_their_visual_rows(self):
        results = [
            (text_box(10, 10, 80, 30), "Biology"),
            (text_box(120, 13, 150, 33), "78"),
            (text_box(220, 8, 250, 28), "100"),
            (text_box(10, 55, 100, 75), "Chemistry"),
            (text_box(120, 53, 150, 73), "85"),
            (text_box(220, 57, 250, 77), "100")
        ]

        self.assertEqual(
            _format_ocr_results(results),
            "Biology 78 100\nChemistry 85 100"
        )

    def test_format_ocr_results_preserves_transcript_table_columns(self):
        results = [
            (text_box(10, 10, 20, 20), "Sl No."),
            (text_box(40, 10, 80, 20), "Name of Subjects"),
            (text_box(90, 10, 120, 20), "Letter Grade"),
            (text_box(130, 10, 160, 20), "Grade Point"),
            (text_box(170, 10, 190, 20), "GPA"),
            (text_box(200, 10, 230, 20), "CGPA"),
            (text_box(10, 35, 20, 45), "1"),
            (text_box(40, 35, 80, 45), "Biology"),
            (text_box(90, 35, 100, 45), "A+"),
            (text_box(140, 35, 150, 45), "5"),
            (text_box(170, 55, 190, 65), "5.00"),
            (text_box(200, 55, 230, 65), "5.00")
        ]

        self.assertEqual(
            _format_ocr_results(results),
            "Sl No. | Name of Subjects | Letter Grade | Grade Point | GPA | CGPA\n"
            "1 | Biology | A+ | 5 |  | \n"
            " |  |  |  | 5.00 | 5.00"
        )

    def test_merge_keeps_unique_lines_and_deduplicates_overlapping_results(self):
        first_line = text_box(10, 10, 110, 30)
        second_line = text_box(10, 50, 130, 70)

        merged = _merge_ocr_results([
            [(first_line, "Invoice", 0.8)],
            [
                (first_line, "Invoice", 0.9),
                (second_line, "Total 20.00", 0.7)
            ],
            [(second_line, "Total 20.00", 0.8)]
        ])

        self.assertEqual(
            [text for _, text in merged],
            ["Invoice", "Total 20.00"]
        )

    def test_merge_prefers_repeated_recognition_over_a_single_high_confidence_error(self):
        box = text_box(10, 10, 110, 30)

        merged = _merge_ocr_results([
            [(box, "Invoice", 0.6)],
            [(box, "Invoice", 0.7)],
            [(box, "Invo1ce", 0.99)]
        ])

        self.assertEqual(merged[0][1], "Invoice")

    def test_extraction_does_not_fallback_at_the_confidence_threshold(self):
        title_box = text_box(10, 10, 110, 30)

        with tempfile.NamedTemporaryFile(suffix=".png") as image_file:
            with patch(
                "image_ocr.cv2.imread",
                return_value=np.zeros((100, 200, 3), dtype=np.uint8)
            ), patch(
                "image_ocr.rapid_reader",
                return_value=([(title_box, "Invoice", 0.4)], 0.01)
            ) as rapid_reader, patch(
                "image_ocr._get_easyocr_reader"
            ) as get_reader:
                extracted = extract_text_from_image(image_file.name)

        rapid_reader.assert_called_once()
        get_reader.assert_not_called()
        self.assertEqual(extracted, "Invoice")

    def test_extraction_uses_one_pass_for_clear_text(self):
        box = text_box(10, 10, 110, 30)

        with tempfile.NamedTemporaryFile(suffix=".png") as image_file:
            with patch(
                "image_ocr.cv2.imread",
                return_value=np.zeros((100, 200, 3), dtype=np.uint8)
            ), patch(
                "image_ocr.rapid_reader",
                return_value=([(box, "Invoice", 0.9)], 0.01)
            ) as rapid_reader, patch(
                "image_ocr._get_easyocr_reader"
            ) as get_reader:
                extracted = extract_text_from_image(image_file.name)

        rapid_reader.assert_called_once()
        get_reader.assert_not_called()
        self.assertEqual(extracted, "Invoice")

    def test_one_low_confidence_cell_does_not_repeat_an_acceptable_read(self):
        first_box = text_box(10, 10, 110, 30)
        second_box = text_box(10, 50, 130, 70)

        with tempfile.NamedTemporaryFile(suffix=".png") as image_file:
            with patch(
                "image_ocr.cv2.imread",
                return_value=np.zeros((100, 200, 3), dtype=np.uint8)
            ), patch(
                "image_ocr.rapid_reader",
                return_value=([
                    (first_box, "Biology", 0.9),
                    (second_box, "78", 0.4)
                ], 0.01)
            ) as rapid_reader, patch(
                "image_ocr._get_easyocr_reader"
            ) as get_reader:
                extracted = extract_text_from_image(image_file.name)

        rapid_reader.assert_called_once()
        get_reader.assert_not_called()
        self.assertEqual(extracted, "Biology\n78")

    def test_extraction_uses_easyocr_when_rapidocr_finds_no_text(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as image_file:
            with patch(
                "image_ocr.cv2.imread",
                return_value=np.zeros((100, 200, 3), dtype=np.uint8)
            ), patch(
                "image_ocr.rapid_reader",
                return_value=([], 0.01)
            ) as rapid_reader, patch(
                "image_ocr._get_easyocr_reader"
            ) as get_reader:
                get_reader.return_value.readtext.return_value = []
                extracted = extract_text_from_image(image_file.name)

        rapid_reader.assert_called_once()
        get_reader.assert_called_once()
        get_reader.return_value.readtext.assert_called_once()
        self.assertEqual(extracted, "")

    def test_extraction_uses_easyocr_for_low_confidence_rapidocr_results(self):
        box = text_box(10, 10, 110, 30)

        with tempfile.NamedTemporaryFile(suffix=".png") as image_file:
            with patch(
                "image_ocr.cv2.imread",
                return_value=np.zeros((100, 200, 3), dtype=np.uint8)
            ), patch(
                "image_ocr.rapid_reader",
                return_value=([(box, "Inv0ice", 0.2)], 0.01)
            ) as rapid_reader, patch(
                "image_ocr._get_easyocr_reader"
            ) as get_reader:
                get_reader.return_value.readtext.return_value = [
                    (box, "Invoice", 0.8)
                ]
                extracted = extract_text_from_image(image_file.name)

        rapid_reader.assert_called_once()
        get_reader.assert_called_once()
        get_reader.return_value.readtext.assert_called_once()
        self.assertEqual(extracted, "Invoice")


if __name__ == "__main__":
    unittest.main()
