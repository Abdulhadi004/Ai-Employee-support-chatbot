
from image_ocr import extract_text_from_image
from document_extractor import extract_document_information

# Step 1: Read text from the image
image_path = "sample.png"

print("\nReading image...")
ocr_text = extract_text_from_image(image_path)

print("\nOCR Text:")
print(ocr_text)

# Step 2: Extract structured information
print("\nUnderstanding document...")

result = extract_document_information(ocr_text)

print("\nStructured Information:")
print("----------------------------")

for key, value in result.items():
    print(f"{key}: {value}")
from document_extractor import redact_sensitive_information

sample_text = """
Name: Ali Ahmed
CNIC: 12345-1234567-1
Card Number: 4111 1111 1111 1111
CVV: 123
PIN: 1234
"""

print("\nOriginal Text:")
print(sample_text)

print("\nRedacted Text:")
print(redact_sensitive_information(sample_text))

sample_text = """
PAKISTAN IDENTITY CARD

Name: Ali Ahmed
Father Name: Ahmed Khan
Date of Birth: 15-05-2000
Gender: Male
CNIC: [REDACTED CNIC]
Issue Date: 15-05-2020
Expiry Date: 15-05-2030
"""

print("\nTesting Identity Card Extraction...")

result = extract_document_information(sample_text)

print("\nStructured Information:")
print(result)
sample_bank_card = """
BANK AL HABIB

Name: Ali Ahmed
Card Type: Debit
Network: VISA
Card Number: [REDACTED CARD NUMBER]
CVV: [REDACTED]
PIN: [REDACTED]
Expiry Date: [REDACTED]
"""

print("\nTesting Bank Card Extraction...")

result = extract_document_information(sample_bank_card)

print("\nStructured Information:")
print(result)
from api import is_payment_card

# Test 1: Bank card
bank_card_text = """
BANK AL HABIB
VISA
Debit Card
Card Number: [REDACTED]
"""

print("\nTest 1 - Bank Card:")
print(is_payment_card(bank_card_text))


# Test 2: Educational document
educational_text = """
Topic: Sense organs
Eyes, ears, nose and tongue.
"""

print("\nTest 2 - Educational Document:")
print(is_payment_card(educational_text))


# Test 3: Identity card
identity_card_text = """
Pakistan Identity Card
Name: Ali Ahmed
Father Name: Ahmed Khan
Date of Birth: 15-05-2000
"""

print("\nTest 3 - Identity Card:")
print(is_payment_card(identity_card_text))