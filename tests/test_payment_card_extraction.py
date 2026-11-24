import unittest

from api import is_payment_card
from document_extractor import (
    extract_bank_card_information,
    extract_document_information,
    is_identity_card_text
)


class PaymentCardExtractionTests(unittest.TestCase):
    def test_extracts_only_safe_bank_card_details(self):
        ocr_text = """
        BANK AL HABIB
        VISA
        DEBIT CARD
        Cardholder Name: Example User
        Card Number: 9999 8888 7777 6666
        Expiry Date: 12/30
        CVV: 123
        PIN: 1234
        """

        self.assertTrue(is_payment_card(ocr_text))
        information = extract_bank_card_information(ocr_text)

        self.assertEqual(
            information,
            {
                "bank_name": "BANK AL HABIB",
                "cardholder_name": "Example User",
                "network": "Visa",
                "card_type": "Debit"
            }
        )
        serialized = repr(information)
        self.assertNotIn("9999", serialized)
        self.assertNotIn("12/30", serialized)
        self.assertNotIn("123", serialized)

    def test_identity_card_number_is_not_misclassified_as_payment_card(self):
        ocr_text = """
        NATIONAL ID CARD
        Card Number: 1234567890123456
        Date of Birth: 01-02-1990
        """

        self.assertTrue(is_identity_card_text(ocr_text))
        self.assertFalse(is_payment_card(ocr_text))
        self.assertEqual(
            extract_document_information(ocr_text)["document_type"],
            "Identity Card"
        )


if __name__ == "__main__":
    unittest.main()
