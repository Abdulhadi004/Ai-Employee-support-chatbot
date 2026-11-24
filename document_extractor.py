
import json

from pydantic import BaseModel, Field
from nodes import llm, extract_response_text
import re

# ========================================
# DOCUMENT INFORMATION MODEL
# ========================================

class ExtractedDocument(BaseModel):
    document_type: str = Field(
        description="Type of document"
    )

    extracted_information: dict[str, object] = Field(
        description="Extracted information. Values can be strings, lists, or numbers."
    )
    
    
def redact_sensitive_information(text: str) -> str:

    # Mask Pakistani CNIC numbers
    text = re.sub(
        r'\b\d{5}[- ]?\d{7}[- ]?\d\b',
        '[REDACTED CNIC]',
        text
    )

    # Mask long card-number-like sequences
    text = re.sub(
        r'(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)',
        '[REDACTED CARD NUMBER]',
        text
    )

    # Mask CVV / CVC
    text = re.sub(
        r'(?i)\b(CVV2?|CVC2?|SECURITY CODE)\s*[:\-]?\s*\d{3,4}\b',
        r'\1: [REDACTED]',
        text
    )

    # Mask PIN
    text = re.sub(
        r'(?i)\bPIN\s*[:\-]?\s*\d{4,6}\b',
        'PIN: [REDACTED]',
        text
    )

    return text


_IDENTITY_FIELD_LABELS = (
    ("father_name", r"father(?:'s)?\s+name"),
    ("date_of_birth", r"(?:date\s+of\s+birth|birth\s+date|dob)"),
    ("issue_date", r"(?:date\s+of\s+issue|issue\s+date|issued\s+on)"),
    (
        "expiry_date",
        r"(?:date\s+of\s+expiry|expiry\s+date|expiration\s+date|valid\s+until)"
    ),
    ("gender", r"(?:gender|sex)"),
    ("country_of_stay", r"country\s+of\s+stay"),
    ("address", r"(?:residential\s+address|address)"),
    ("name", r"(?:full\s+name|name)")
)
_IDENTITY_DATE_PATTERN = re.compile(
    r"(?<!\d)(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}"
    r"|\d{4}[./-]\d{1,2}[./-]\d{1,2})(?!\d)"
)


def is_identity_card_text(text: str) -> bool:
    if re.search(
        r"\b(?:(?:pakistan|national)\s+)?identity\s+card\b|"
        r"\b(?:national|government)\s+id(?:entity)?(?:\s+card)?\b|"
        r"\bid\s+card\b|\bidentity\s+document\b|\bcnic\b",
        text,
        re.IGNORECASE
    ):
        return True

    has_birth_date = re.search(
        r"\b(?:date\s+of\s+birth|birth\s+date|dob)\b",
        text,
        re.IGNORECASE
    ) is not None
    has_issue_or_expiry_date = re.search(
        r"\b(?:issue\s+date|date\s+of\s+issue|expiry\s+date|"
        r"date\s+of\s+expiry|expiration\s+date)\b",
        text,
        re.IGNORECASE
    ) is not None
    has_father_name = re.search(
        r"\bfather(?:'s)?\s+name\b",
        text,
        re.IGNORECASE
    ) is not None
    has_id_number = re.search(
        r"\b(?:id|identity)\s*(?:number|no\.?|#)(?=\W|$)",
        text,
        re.IGNORECASE
    ) is not None
    has_gender = re.search(
        r"\b(?:gender|sex)\b",
        text,
        re.IGNORECASE
    ) is not None

    return (
        (has_father_name and has_birth_date and has_issue_or_expiry_date)
        or (has_birth_date and has_id_number)
        or (has_gender and has_id_number)
    )


def _find_identity_field_labels(line: str):
    matches = []
    for field, pattern in _IDENTITY_FIELD_LABELS:
        for match in re.finditer(rf"\b(?:{pattern})\b", line, re.IGNORECASE):
            matches.append((match.start(), match.end(), field))

    selected = []
    for match in sorted(
        matches,
        key=lambda item: (item[0], -(item[1] - item[0]))
    ):
        if any(
            match[0] < existing[1] and match[1] > existing[0]
            for existing in selected
        ):
            continue
        selected.append(match)

    return sorted(selected)


def _extract_identity_card_information(ocr_text: str) -> dict[str, str]:
    lines = [line.strip() for line in ocr_text.splitlines()]
    information = {}
    date_fields = {"date_of_birth", "issue_date", "expiry_date"}

    for line_index, line in enumerate(lines):
        labels = _find_identity_field_labels(line)
        pending_fields = []

        for label_index, (_, end, field) in enumerate(labels):
            value_end = (
                labels[label_index + 1][0]
                if label_index + 1 < len(labels)
                else len(line)
            )
            value = line[end:value_end].strip(" \t:;|#-")

            if field in date_fields:
                date_match = _IDENTITY_DATE_PATTERN.search(value)
                if date_match is not None:
                    value = date_match.group()
                else:
                    pending_fields.append(field)
                    continue
            elif not value:
                pending_fields.append(field)
                continue

            if field == "gender" and value.casefold() not in {
                "m", "male", "f", "female", "other"
            }:
                continue

            if value and field not in information:
                information[field] = value

        if not pending_fields or line_index + 1 >= len(lines):
            continue

        next_line = lines[line_index + 1]
        if _find_identity_field_labels(next_line):
            continue

        if all(field in date_fields for field in pending_fields):
            dates = _IDENTITY_DATE_PATTERN.findall(next_line)
            if len(dates) == len(pending_fields):
                for field, value in zip(pending_fields, dates):
                    information.setdefault(field, value)
            continue

        if pending_fields == ["gender", "country_of_stay"]:
            gender_match = re.match(
                r"^\s*(male|female|m|f|other)\b(?:[\s|,:;-]+(.*))?$",
                next_line,
                re.IGNORECASE
            )
            if gender_match:
                information.setdefault("gender", gender_match.group(1))
                country = gender_match.group(2).strip(" \t:;|#-")
                if country:
                    information.setdefault("country_of_stay", country)
            continue

        if len(pending_fields) == 1:
            field = pending_fields[0]
            value = next_line.strip(" \t:;|#-")
            if field == "gender":
                if value.casefold() not in {"m", "male", "f", "female", "other"}:
                    continue
            elif field in {"name", "father_name"} and re.search(r"\d", value):
                continue
            if value:
                information.setdefault(field, value)

    return information


def extract_bank_card_information(ocr_text: str) -> dict[str, str]:
    lines = [line.strip() for line in ocr_text.splitlines() if line.strip()]
    information = {}

    network_patterns = (
        ("American Express", r"\b(?:american\s+express|amex)\b"),
        ("Mastercard", r"\bmaster\s*card\b|\bmastercard\b"),
        ("Visa", r"\bvisa\b"),
        ("Discover", r"\bdiscover\b"),
        ("UnionPay", r"\bunion\s*pay\b"),
        ("RuPay", r"\brupay\b"),
        ("JCB", r"\bjcb\b"),
        ("Diners Club", r"\bdiners?\s+club\b")
    )

    for line in lines:
        bank_match = re.match(
            r"^\s*(?:issuing\s+)?bank(?:\s+name)?"
            r"\s*[:\-]\s*(.+)$",
            line,
            re.IGNORECASE
        )
        if bank_match and bank_match.group(1).strip():
            bank_name = bank_match.group(1).strip()
            if not re.search(
                r"\d|\b(?:cvv|cvc|pin|expiry|expiration|card\s+number)\b",
                bank_name,
                re.IGNORECASE
            ):
                information.setdefault("bank_name", bank_name)
        elif re.match(r"^\s*bank\s+", line, re.IGNORECASE) and not re.match(
            r"^\s*bank\s+card\b",
            line,
            re.IGNORECASE
        ):
            if not re.search(r"\d", line):
                information.setdefault("bank_name", line)

        holder_match = re.search(
            r"\b(?:cardholder(?:\s+name)?|card\s*holder(?:\s+name)?|"
            r"name\s+on\s+(?:the\s+)?card|full\s+name)"
            r"\s*[:\-]\s*(.+)$",
            line,
            re.IGNORECASE
        )
        if holder_match is None:
            holder_match = re.match(
                r"^\s*name\s*[:\-]\s*(.+)$",
                line,
                re.IGNORECASE
            )
        if holder_match:
            holder_name = holder_match.group(1).strip()
            if (
                holder_name
                and not re.search(r"\d", holder_name)
                and not re.search(
                    r"\b(?:cvv|cvc|pin|expiry|expiration|card\s+number)\b",
                    holder_name,
                    re.IGNORECASE
                )
            ):
                information.setdefault("cardholder_name", holder_name)

    for network, pattern in network_patterns:
        if re.search(pattern, ocr_text, re.IGNORECASE):
            information["network"] = network
            break

    card_type = re.search(
        r"\b(debit|credit|prepaid)(?:\s+card)?\b",
        ocr_text,
        re.IGNORECASE
    )
    if card_type:
        information["card_type"] = card_type.group(1).title()

    return information


_MARKSHEET_FIELD_LABELS = (
    (
        "student_name",
        r"(?:student(?:'s)?\s+name|name\s+of\s+(?:the\s+)?student|"
        r"name(?!\s*of\s*(?:institution|college|school|subjects?)))"
    ),
    ("father_name", r"(?:father(?:'s)?\s+name|name\s+of\s+father)"),
    ("mother_name", r"(?:mother(?:'s)?\s+name|name\s+of\s+mother)"),
    (
        "institution",
        r"(?:name\s+of\s+(?:the\s+)?(?:institution|college|school)|"
        r"(?:school|college|institution|institute)(?:\s+name)?)"
    ),
    ("roll_number", r"roll\s*(?:number|no\.?|#)"),
    ("registration_number", r"(?:registration|reg)\s*(?:number|no\.?|#)"),
    ("class_or_grade", r"(?:class\s*/\s*grade|class|standard)"),
    ("board", r"(?:education\s+)?board"),
    ("exam_name", r"(?:exam(?:ination)?(?:\s+name)?|test)"),
    ("academic_year", r"(?:academic\s+year|session|year)"),
    ("date_of_birth", r"(?:date\s+of\s+birth|birth\s+date|dob)"),
    ("result_date", r"(?:result\s+date|date\s+of\s+result)"),
    ("group", r"group"),
    ("type_of_student", r"type\s+of\s+student"),
    ("percentage", r"(?:percentage|percent)"),
    ("grade", r"(?:(?:overall|letter)\s+)?grade(?!\s+point)"),
    ("result_status", r"(?:result|status)"),
    ("marks_obtained", r"(?:marks?\s+obtained|obtained\s+marks|marks?\s+scored)"),
    ("total_marks", r"(?:maximum\s+marks|max(?:imum)?\s+marks)")
)
_MARKSHEET_NUMBER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])[0-9]+(?:\.[0-9]+)?"
    r"(?:\s*/\s*[0-9]+(?:\.[0-9]+)?)*(?![A-Za-z0-9])"
)
_MARKSHEET_LETTER_GRADE_PATTERN = re.compile(
    r"(?<![A-Za-z])[A-F][+-]?(?![A-Za-z])",
    re.IGNORECASE
)


def _is_marksheet_text(text: str) -> bool:
    if re.search(
        r"\bmark[\s-]*sheet\b|\bstatement\s+of\s+marks\b|"
        r"\bacademic\s+transcript\b|\bresult\s+card\b",
        text,
        re.IGNORECASE
    ):
        return True

    if re.search(
        r"\bboard\b.{0,80}\bsecondary\b.{0,40}\beducation\b",
        text,
        re.IGNORECASE
    ):
        return True

    if (
        re.search(
            r"\bsubject[\s-]*wise.{0,80}(?:detail|marks?)",
            text,
            re.IGNORECASE
        )
        and re.search(r"maximum|obtained", text, re.IGNORECASE)
    ):
        return True

    if (
        re.search(
            r"\bname\s*of\s*the\s*subjects?\b",
            text,
            re.IGNORECASE
        )
        and re.search(
            r"maximum.{0,50}obtained",
            text,
            re.IGNORECASE
        )
    ):
        return True

    if (
        re.search(r"\bsubjects?\b", text, re.IGNORECASE)
        and re.search(
            r"\b(?:letter\s+grade|grade\s+point|gpa|cgpa)\b",
            text,
            re.IGNORECASE
        )
    ):
        return True

    return all(
        re.search(pattern, text, re.IGNORECASE) is not None
        for pattern in (
            r"\bsubject\b",
            r"\b(?:marks?|obtained|percentage)\b",
            r"\b(?:student|roll|result)\b"
        )
    )


def _parse_marks_value(value: str):
    parts = [part.strip() for part in value.split("/")]
    if len(parts) == 2:
        return parts[0], parts[1]
    return None


def _extract_marksheet_information(ocr_text: str) -> dict[str, object]:
    lines = [line.strip() for line in ocr_text.splitlines() if line.strip()]
    information = {}
    subjects = []
    transcript_columns = None
    transcript_gpa_values = {}
    maximum_marks_precede_obtained = re.search(
        r"maximum.{0,50}obtained",
        ocr_text,
        re.IGNORECASE
    ) is not None

    total_pattern = re.compile(
        r"^\s*(?:grand\s+)?total(?:\s+marks?)?\s*[:\-|]?\s*(.+)$",
        re.IGNORECASE
    )

    for line in lines:
        if "|" in line:
            cells = [cell.strip() for cell in line.split("|")]
            if transcript_columns is None:
                subject_column = next(
                    (
                        index for index, cell in enumerate(cells)
                        if re.search(r"\bsubjects?\b", cell, re.IGNORECASE)
                    ),
                    None
                )
                letter_grade_column = next(
                    (
                        index for index, cell in enumerate(cells)
                        if re.search(r"\bletter\s+grade\b", cell, re.IGNORECASE)
                    ),
                    None
                )
                grade_point_column = next(
                    (
                        index for index, cell in enumerate(cells)
                        if re.search(r"\bgrade\s+poin", cell, re.IGNORECASE)
                    ),
                    None
                )
                gpa_columns = [
                    index for index, cell in enumerate(cells)
                    if re.fullmatch(r"(?:gpa|cgpa)", cell, re.IGNORECASE)
                ]
                if (
                    subject_column is not None
                    and letter_grade_column is not None
                    and grade_point_column is not None
                    and gpa_columns
                ):
                    transcript_columns = {
                        "subject": subject_column,
                        "letter_grade": letter_grade_column,
                        "grade_point": grade_point_column,
                        "gpa": gpa_columns
                    }
                    transcript_gpa_values = {
                        index: []
                        for index in gpa_columns
                    }
                    subjects.clear()
                    continue

            if transcript_columns is not None:
                for index in transcript_columns["gpa"]:
                    if index < len(cells) and re.fullmatch(
                        r"[0-9]+(?:\.[0-9]+)?",
                        cells[index]
                    ):
                        transcript_gpa_values[index].append(cells[index])

                subject_index = transcript_columns["subject"]
                grade_index = transcript_columns["letter_grade"]
                point_index = transcript_columns["grade_point"]
                if subject_index < len(cells):
                    subject = cells[subject_index]
                    grade_cell = (
                        cells[grade_index].rstrip(".")
                        if grade_index < len(cells)
                        else ""
                    )
                    grade_match = (
                        re.fullmatch(
                            r"[A-F][+-]?",
                            grade_cell,
                            re.IGNORECASE
                        )
                        if grade_index < len(cells)
                        else None
                    )
                    grade_cell_has_text = (
                        grade_index < len(cells)
                        and bool(grade_cell)
                    )
                    if (
                        (grade_match or grade_cell_has_text)
                        and len(re.findall(r"[A-Za-z]", subject)) >= 3
                    ):
                        subject_result: dict[str, object] = {"subject": subject}
                        if grade_match:
                            subject_result["letter_grade"] = grade_match.group()
                        if point_index < len(cells):
                            grade_point = cells[point_index]
                            if re.fullmatch(r"[Ss]\.?", grade_point):
                                grade_point = "5"
                            if re.fullmatch(
                                r"[0-9]+(?:\.[0-9]+)?",
                                grade_point
                            ):
                                subject_result["grade_point"] = grade_point
                        subjects.append(subject_result)
                continue

        gpa_matches = re.findall(
            r"\b(GPA|CGPA)\s*[:\-|]\s*([0-9]+(?:\.[0-9]+)?)",
            line,
            re.IGNORECASE
        )
        for field, value in gpa_matches:
            information.setdefault(field.lower(), value)

        if re.search(
            r"\b(?:name\s+of\s+subjects|letter\s+grade|grade\s+point)\b",
            line,
            re.IGNORECASE
        ):
            continue
        if (
            re.search(
                r"(?:subject[\s-]*wise|name\s*of\s*the\s*subjects?)",
                line,
                re.IGNORECASE
            )
            and re.search(r"maximum|obtained", line, re.IGNORECASE)
        ):
            continue

        total_match = total_pattern.match(line)
        if total_match:
            numbers = _MARKSHEET_NUMBER_PATTERN.findall(total_match.group(1))
            parsed_total = (
                _parse_marks_value(numbers[0])
                if numbers
                else None
            )
            if parsed_total:
                information["marks_obtained"] = parsed_total[0]
                information["total_marks"] = parsed_total[1]
            elif len(numbers) >= 2:
                information["marks_obtained"] = numbers[0]
                information["total_marks"] = numbers[1]
            continue

        for field, label_pattern in _MARKSHEET_FIELD_LABELS:
            match = re.match(
                rf"^\s*(?:{label_pattern})\s*[:\-|]?\s*(.*?)\s*$",
                line,
                re.IGNORECASE
            )
            if match and match.group(1):
                if field == "institution" and not re.match(
                    r"^\s*(?:name\s+of\s+(?:the\s+)?(?:institution|"
                    r"college|school)|school(?:\s+name)?|college(?:\s+name)?|"
                    r"institution(?:\s+name)?|institute(?:\s+name)?)\s*[:\-|]",
                    line,
                    re.IGNORECASE
                ):
                    continue
                information.setdefault(field, match.group(1).strip())
                break

        if re.search(r"\bGPA\b.*\bCGPA\b", line, re.IGNORECASE):
            values = _MARKSHEET_NUMBER_PATTERN.findall(line)
            if len(values) >= 2:
                information.setdefault("gpa", values[0])
                information.setdefault("cgpa", values[1])

        if re.search(
            r"\b(?:total|grand|overall|percentage|percent|result|grade|"
            r"gpa|cgpa|pass|fail|marks?\s+obtained|date|birth|cnic|passport|"
            r"national\s+id|phone|mobile|contact)\b",
            line,
            re.IGNORECASE
        ):
            continue

        row_text = re.sub(r"^\s*[.)]?\d+[.)]?\s+", "", line)
        number_matches = list(_MARKSHEET_NUMBER_PATTERN.finditer(row_text))
        letter_grade = _MARKSHEET_LETTER_GRADE_PATTERN.search(row_text)
        if letter_grade:
            numbers_after_grade = [
                match
                for match in number_matches
                if match.start() >= letter_grade.end()
            ]
            numbers_before_grade = [
                match
                for match in number_matches
                if match.end() <= letter_grade.start()
            ]
            if not numbers_before_grade:
                subject = row_text[:letter_grade.start()].strip(" \t:;|#-")
                additional_subject = bool(
                    re.match(r"^\s*additional\s+subject\b", subject, re.I)
                )
                subject = re.sub(
                    r"^\s*additional\s+subject\s*[:\-|]?\s*",
                    "",
                    subject,
                    flags=re.IGNORECASE
                )
                subject = re.sub(r"^[.)]?\d+[.)]?\s*", "", subject).strip()
                if len(re.findall(r"[A-Za-z]", subject)) >= 3:
                    subject_result: dict[str, object] = {
                        "subject": subject,
                        "letter_grade": letter_grade.group()
                    }
                    if numbers_after_grade:
                        subject_result["grade_point"] = (
                            numbers_after_grade[0].group()
                        )
                    if additional_subject:
                        subject_result["additional_subject"] = True
                    subjects.append(subject_result)
                    continue

        if not number_matches:
            continue

        subject = row_text[:number_matches[0].start()].strip(" \t:;|#-")
        if len(re.findall(r"[A-Za-z]", subject)) < 3:
            continue

        mark_pair = _parse_marks_value(number_matches[0].group())
        if mark_pair is None and len(number_matches) >= 2:
            first_mark = number_matches[0].group()
            second_mark = number_matches[1].group()
            mark_pair = (
                (second_mark, first_mark)
                if maximum_marks_precede_obtained
                else (first_mark, second_mark)
            )
        if mark_pair is None:
            continue

        subject_result: dict[str, object] = {
            "subject": subject,
            "marks_obtained": mark_pair[0],
            "total_marks": mark_pair[1]
        }
        last_mark_end = (
            number_matches[0].end()
            if "/" in number_matches[0].group()
            else number_matches[1].end()
        )
        trailing_text = row_text[last_mark_end:].strip(" \t:;|#-/")
        grade_match = re.fullmatch(r"[A-F][+-]?|PASS|FAIL", trailing_text, re.I)
        if grade_match:
            subject_result["grade"] = trailing_text
        subjects.append(subject_result)

    if subjects:
        information["subjects"] = subjects
    if transcript_columns is not None and len(transcript_columns["gpa"]) >= 2:
        gpa_column, cgpa_column = transcript_columns["gpa"][:2]
        if transcript_gpa_values[gpa_column]:
            information.setdefault(
                "gpa",
                transcript_gpa_values[gpa_column][0]
            )
        if transcript_gpa_values[cgpa_column]:
            information.setdefault(
                "cgpa",
                transcript_gpa_values[cgpa_column][0]
            )

    return information


# ========================================
# EXTRACT STRUCTURED INFORMATION
# ========================================

def extract_document_information(ocr_text: str):

    if not ocr_text.strip():
        return {
            "document_type": "Unknown",
            "extracted_information": {},
            "message": "No readable text found in the image."
        }

    if is_identity_card_text(ocr_text):
        return {
            "document_type": "Identity Card",
            "extracted_information": _extract_identity_card_information(ocr_text)
        }

    if _is_marksheet_text(ocr_text):
        information = _extract_marksheet_information(ocr_text)
        if not information.get("subjects"):
            information["recognized_text"] = redact_sensitive_information(
                ocr_text
            )
            return {
                "document_type": "Marksheet",
                "extracted_information": information,
                "message": (
                    "Marksheet detected, but subject rows could not be "
                    "confidently read. OCR text is included for review."
                )
            }
        return {
            "document_type": "Marksheet",
            "extracted_information": information
        }

    # Redact sensitive information before sending text to Groq.
    safe_ocr_text = redact_sensitive_information(ocr_text)

    prompt = f"""
    You are a document information extraction assistant.

    Analyze the OCR text extracted from a document.

    Identify the document type using these categories:

1. Identity Card
2. Bank Card
3. Bank Statement
4. Receipt
5. Invoice
6. Marksheet
7. Certificate
8. Business Card
9. Meeting Invitation
10. Event Invitation
11. Schedule
12. Educational Poster
13. Educational Notes
14. Screenshot
15. General Document
16. Other

    Extract only information explicitly present in the text.

    Rules:
    1. Never guess missing information.
    2. Do not invent names, dates, or numbers.
    3. Preserve the original values.
    4. Use English field names.
    5. If a field is missing, do not include it.
    6. Never extract or return CVV, PIN, passwords,
       or full payment card numbers.
    7. For bank cards, identify only safe information,
       such as card network or issuing bank if visible.
    8. If the document is unclear, state that information
       could not be identified.
    9. Never extract full CNIC numbers, national ID numbers,
       passport numbers, full bank card numbers, CVVs,
       PINs, passwords, or full bank account numbers.
    10. Do not reproduce sensitive numbers even if they
       are clearly visible in the OCR text.
    12. For meeting invitations, extract:
    - meeting_platform
    - meeting_link
    - meeting_id
    - meeting_date
    - meeting_time
    - passcode

13. For schedules, extract dates, times, and events.

14. Extract only information explicitly visible in the OCR text.
15. Classify result sheets and academic marks tables as Marksheet. Use
    Educational Poster or Educational Notes only for teaching material.

16. Extract important headings, topics, advantages,
    disadvantages, and bullet points from educational material.

17. Do not reject a document simply because some OCR words
    are unclear.

18. If some words are unclear, extract the readable words
    and ignore the unclear parts.

19. For educational material, use fields such as:
    - topic
    - headings
    - advantages
    - disadvantages
    - main_points
    
    DOCUMENT-SPECIFIC EXTRACTION RULES:

1. Identity Card:
   - Extract document type.
   - Extract name.
   - Extract father's name, if visible.
   - Extract date of birth, if visible.
   - Extract gender, if visible.
   - Extract issue date and expiry date, if visible.
   - Extract address, if visible.
   - Never reveal or reconstruct the CNIC number.
   - If a CNIC number appears, report it as "[REDACTED]".

2. Bank Card:
   - Extract bank name, if visible.
   - Extract cardholder name, if visible.
   - Identify card network (Visa, Mastercard, etc.), if visible.
   - Identify card type (Debit or Credit), if visible.
   - Never extract or reveal the card number.
   - Never extract CVV, CVC, PIN, or expiry date.
   - Never guess missing information.

3. Educational Notes:
   - Extract topic, headings, and main points.

4. Marksheet or Academic Transcript:
   - Classify it as "Marksheet".
   - Extract every readable student and exam field, including student_name,
     roll_number, registration_number, class_or_grade, board, institution,
     exam_name, academic_year, and result_date when present.
   - Extract each subject as a separate item in a "subjects" list. Include
     subject, marks_obtained, total_marks, and grade only when printed.
   - Extract overall marks_obtained, total_marks, percentage, grade, and
     result_status only when explicitly printed.
   - Treat each OCR line as one visual table row. Keep subject names and marks
     from that same row together, and do not move marks between subjects.
   - Return all readable rows and fields, not just the document type or title.
   - Never calculate totals, percentages, grades, or missing values.
   - Omit unclear or absent values instead of guessing.

5. General Documents:
   - Extract only clearly visible and relevant information.

IMPORTANT:
- Use only the redacted OCR text provided.
- Never guess missing information.
- Never reconstruct masked sensitive information.

    Return ONLY valid JSON with exactly these top-level keys:
    "document_type" (string) and "extracted_information" (object).
    For a marksheet, use a "subjects" list of objects so each subject's marks
    remain associated with its subject. Omit every field not visible in OCR;
    do not copy field names as values.

    OCR TEXT:
    {safe_ocr_text}
    """

    try:
        
        result = llm.invoke(prompt)

        content = extract_response_text(result.content)

        content = content.replace("```json", "").replace("```", "").strip()

        start = content.find("{")
        end = content.rfind("}")

        if start == -1 or end == -1:
            raise ValueError("Invalid JSON response from LLM.")

        data = json.loads(content[start:end + 1])

        validated = ExtractedDocument.model_validate(data)

        return validated.model_dump()

    except Exception as e:

        print(f"Document extraction error: {e}")

        return {
            "document_type": "Unknown",
            "extracted_information": {},
            "message": "Could not extract document information."
        }
