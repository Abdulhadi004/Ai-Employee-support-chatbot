import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from document_extractor import extract_document_information


class MarksheetExtractionTests(unittest.TestCase):
    def test_detects_condensed_subject_wise_maximum_obtained_table(self):
        ocr_text = """
        SUBJECT-WISEDETAILOFMARKSOBTAINED
        S.NO NAMEOFTHESUBJECT MAXIMUM OBTAINED
        1 ENGLISH(COMPULSORY) 150 067
        2 URDU(COMPULSORY) 150 084
        3 PAKISTAN STUDIES 075 057
        """

        with patch("document_extractor.llm") as llm:
            result = extract_document_information(ocr_text)

        llm.invoke.assert_not_called()
        self.assertEqual(result["document_type"], "Marksheet")
        information = result["extracted_information"]
        self.assertNotIn("student_name", information)
        self.assertEqual(
            information["subjects"],
            [
                {
                    "subject": "ENGLISH(COMPULSORY)",
                    "marks_obtained": "067",
                    "total_marks": "150"
                },
                {
                    "subject": "URDU(COMPULSORY)",
                    "marks_obtained": "084",
                    "total_marks": "150"
                },
                {
                    "subject": "PAKISTAN STUDIES",
                    "marks_obtained": "057",
                    "total_marks": "075"
                }
            ]
        )

    def test_table_columns_keep_grade_points_and_overall_gpa_separate(self):
        ocr_text = """
        BOARD OF INTERMEDIATE AND SECONDARY EDUCATION
        apng jo SueN F
        Sl No. | Name of Subjects | Letter Grade | Grade Point | GPA | GPA
        1 | Bangla | A+ | 5 |  |
         2 | English | A. | 5 | 5.00 |
         3 | Mathematics | A+ | S. |  |
         |  |  |  |  | 5.00
        """

        with patch("document_extractor.llm") as llm:
            result = extract_document_information(ocr_text)

        llm.invoke.assert_not_called()
        information = result["extracted_information"]
        self.assertEqual(information["gpa"], "5.00")
        self.assertEqual(information["cgpa"], "5.00")
        self.assertEqual(
            information["subjects"],
            [
                {
                    "subject": "Bangla",
                    "letter_grade": "A+",
                    "grade_point": "5"
                },
                {
                    "subject": "English",
                    "letter_grade": "A",
                    "grade_point": "5"
                },
                {
                    "subject": "Mathematics",
                    "letter_grade": "A+",
                    "grade_point": "5"
                }
            ]
        )

    def test_detects_transcript_table_from_column_headers(self):
        ocr_text = """
        Mame of Subjects Letter Grade Grade Poiny GPA GPA
        2 Engsn. A. 5
        .3 Witenaks A+ S.
        4 Seclusdeoce A+ 5.00 5.00
        """

        with patch("document_extractor.llm") as llm:
            result = extract_document_information(ocr_text)

        llm.invoke.assert_not_called()
        self.assertEqual(result["document_type"], "Marksheet")
        self.assertEqual(
            [row["subject"] for row in result["extracted_information"]["subjects"]],
            ["Engsn.", "Witenaks", "Seclusdeoce"]
        )

    def test_title_only_marksheet_returns_ocr_text_instead_of_unknown(self):
        ocr_text = "MARKSHEET\nAnnual Examination"

        with patch("document_extractor.llm") as llm:
            result = extract_document_information(ocr_text)

        llm.invoke.assert_not_called()
        self.assertEqual(result["document_type"], "Marksheet")
        self.assertEqual(
            result["extracted_information"]["recognized_text"],
            ocr_text
        )
        self.assertIn("could not be confidently read", result["message"])

    def test_extracts_marked_rows_without_calling_the_llm(self):
        ocr_text = """
        SCHOOL MARKSHEET
        Student Name: Sana Noor
        Roll No: 2045
        Date of Birth: 11-07-2000
        Subject Obtained Total Grade
        Biology 78 100 A
        Chemistry 85 100 B+
        Total Marks: 163 / 200
        Percentage: 81.5%
        Result: PASS
        """

        with patch("document_extractor.llm") as llm:
            result = extract_document_information(ocr_text)

        llm.invoke.assert_not_called()
        self.assertEqual(result["document_type"], "Marksheet")
        self.assertEqual(
            result["extracted_information"],
            {
                "student_name": "Sana Noor",
                "roll_number": "2045",
                "date_of_birth": "11-07-2000",
                "percentage": "81.5%",
                "result_status": "PASS",
                "marks_obtained": "163",
                "total_marks": "200",
                "subjects": [
                    {
                        "subject": "Biology",
                        "marks_obtained": "78",
                        "total_marks": "100",
                        "grade": "A"
                    },
                    {
                        "subject": "Chemistry",
                        "marks_obtained": "85",
                        "total_marks": "100",
                        "grade": "B+"
                    }
                ]
            }
        )

    def test_extracts_letter_grades_and_grade_points_from_transcript_rows(self):
        ocr_text = """
        BOARD OF INTERMEDIATE AND SECONDARY EDUCATION DHAKA
        ACADEMIC TRANSCRIPT
        Name of Student: Sana Noor
        Father's Name: Amir Noor
        Mother's Name: Sara Noor
        Name of Institution: Example High School
        Roll No.: 2045
        Registration No.: 9876
        Group: Science
        Type of Student: Regular
        Date of Birth: 11-07-2000
        Sl No. Name of Subjects Letter Grade Grade Point GPA CGPA
        1. Bangla A+ 5
        2. English A+ 5
        3. Mathematics A+ 5
        GPA: 5.00
        CGPA: 5.00
        """

        with patch("document_extractor.llm") as llm:
            result = extract_document_information(ocr_text)

        llm.invoke.assert_not_called()
        self.assertEqual(result["document_type"], "Marksheet")
        information = result["extracted_information"]
        self.assertEqual(information["student_name"], "Sana Noor")
        self.assertEqual(information["father_name"], "Amir Noor")
        self.assertEqual(information["mother_name"], "Sara Noor")
        self.assertEqual(information["institution"], "Example High School")
        self.assertEqual(information["roll_number"], "2045")
        self.assertEqual(information["registration_number"], "9876")
        self.assertEqual(information["group"], "Science")
        self.assertEqual(information["type_of_student"], "Regular")
        self.assertEqual(information["date_of_birth"], "11-07-2000")
        self.assertEqual(information["gpa"], "5.00")
        self.assertEqual(information["cgpa"], "5.00")
        self.assertEqual(
            information["subjects"],
            [
                {
                    "subject": "Bangla",
                    "letter_grade": "A+",
                    "grade_point": "5"
                },
                {
                    "subject": "English",
                    "letter_grade": "A+",
                    "grade_point": "5"
                },
                {
                    "subject": "Mathematics",
                    "letter_grade": "A+",
                    "grade_point": "5"
                }
            ]
        )

    def test_prompt_requests_all_subject_rows_and_preserves_mark_association(self):
        ocr_text = """
        EXAM RECORD
        Subject: Biology
        Marks are not legible.
        """
        response = {
            "document_type": "Marksheet",
            "extracted_information": {
                "student_name": "Sana Noor",
                "subjects": [
                    {
                        "subject": "Biology",
                        "marks_obtained": "78",
                        "total_marks": "100"
                    },
                    {
                        "subject": "Chemistry",
                        "marks_obtained": "85",
                        "total_marks": "100"
                    }
                ],
                "marks_obtained": "163",
                "total_marks": "200"
            }
        }

        with patch("document_extractor.llm") as llm:
            llm.invoke.return_value = SimpleNamespace(
                content=json.dumps(response)
            )
            result = extract_document_information(ocr_text)

        prompt = llm.invoke.call_args.args[0]
        self.assertIn("Marksheet or Academic Transcript", prompt)
        self.assertIn(
            "Classify result sheets and academic marks tables as Marksheet",
            prompt
        )
        self.assertIn("Return all readable rows and fields", prompt)
        self.assertIn("do not move marks between subjects", prompt)
        self.assertEqual(result, response)


if __name__ == "__main__":
    unittest.main()
