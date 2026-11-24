import unittest
from unittest.mock import patch

from document_extractor import extract_document_information


class IdentityCardExtractionTests(unittest.TestCase):
    def test_recognizes_id_card_with_partial_identity_fields(self):
        ocr_text = """
        ID CARD
        Name: Example Person
        Date of Birth: 11-07-1990
        """

        with patch("document_extractor.llm") as llm:
            result = extract_document_information(ocr_text)

        llm.invoke.assert_not_called()
        self.assertEqual(result["document_type"], "Identity Card")
        self.assertEqual(
            result["extracted_information"],
            {
                "name": "Example Person",
                "date_of_birth": "11-07-1990"
            }
        )

    def test_extracts_only_labeled_fields_without_calling_the_llm(self):
        ocr_text = """
        PAKISTAN IDENTITY CARD
        Name: Sana Noor
        Father Name: Amir Noor
        Date of Birth: 11-07-1990
        Gender: Female
        Date of Issue: 12-03-2021 Date of Expiry: 12-03-2031
        """

        with patch("document_extractor.llm") as llm:
            result = extract_document_information(ocr_text)

        llm.invoke.assert_not_called()
        self.assertEqual(result["document_type"], "Identity Card")
        self.assertEqual(
            result["extracted_information"],
            {
                "name": "Sana Noor",
                "father_name": "Amir Noor",
                "date_of_birth": "11-07-1990",
                "gender": "Female",
                "issue_date": "12-03-2021",
                "expiry_date": "12-03-2031"
            }
        )
        self.assertNotIn("address", result["extracted_information"])

    def test_accepts_dates_on_the_line_after_their_labels(self):
        ocr_text = """
        NATIONAL IDENTITY CARD
        Issue Date:
        12-03-2021
        Expiry Date:
        12-03-2031
        """

        result = extract_document_information(ocr_text)

        self.assertEqual(
            result["extracted_information"],
            {
                "issue_date": "12-03-2021",
                "expiry_date": "12-03-2031"
            }
        )

    def test_does_not_treat_country_of_stay_heading_as_gender(self):
        ocr_text = """
        NATIONAL IDENTITY CARD
        Gender Country of Stay
        """

        result = extract_document_information(ocr_text)

        self.assertEqual(result["extracted_information"], {})

    def test_separates_gender_and_country_of_stay_on_the_same_line(self):
        ocr_text = """
        NATIONAL IDENTITY CARD
        Gender Female Country of Stay Pakistan
        """

        result = extract_document_information(ocr_text)

        self.assertEqual(
            result["extracted_information"],
            {
                "gender": "Female",
                "country_of_stay": "Pakistan"
            }
        )

    def test_extracts_values_on_following_lines_and_pairs_dates(self):
        ocr_text = """
        PAKISTAN NATIONAL IDENTITY CARD
        Name
        Example Person
        Father Name
        Example Parent
        Gender Country of Stay
        F Pakistan
        Identity Number
        1234567890123
        Date of Issue Date of Expiry
        12-03-2021 12-03-2031
        """

        result = extract_document_information(ocr_text)

        self.assertEqual(
            result["extracted_information"],
            {
                "name": "Example Person",
                "father_name": "Example Parent",
                "gender": "F",
                "country_of_stay": "Pakistan",
                "issue_date": "12-03-2021",
                "expiry_date": "12-03-2031"
            }
        )

    def test_returns_address_only_when_it_is_explicitly_labeled(self):
        ocr_text = """
        PAKISTAN IDENTITY CARD
        Name: Sana Noor
        Address: 10 Example Road
        """

        result = extract_document_information(ocr_text)

        self.assertEqual(
            result["extracted_information"],
            {
                "name": "Sana Noor",
                "address": "10 Example Road"
            }
        )


if __name__ == "__main__":
    unittest.main()
