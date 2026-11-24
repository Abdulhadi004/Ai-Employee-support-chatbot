
from pathlib import Path
from uuid import uuid4
import sqlite3
import re
from fastapi import (
    FastAPI,
    HTTPException,
    Depends,
    status,
    UploadFile,
    File,
    Form,
    Query
)

import tempfile
from datetime import date, time
from typing import Literal
from PIL import Image
from io import BytesIO
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr, Field

from graph import app as graph_app

from auth import (
    create_user,
    delete_user_account,
    authenticate_user,
    create_access_token,
    get_current_user,
    require_roles,
    set_user_role
)

from chat_db import (
    create_conversation,
    get_user_conversation,
    save_message,
    get_user_conversations,
    get_conversation_messages,
    delete_conversation
)

from user_memory import (
    get_user_memories as fetch_user_memories,
    save_user_memory,
    delete_user_memory,
    delete_all_user_memories
)

from hr_db import (
    approve_employee_registration,
    create_department,
    create_employee_registration,
    create_employee,
    create_leave_request,
    deactivate_employee,
    department_exists,
    get_chat_employee_context,
    get_dashboard_stats,
    get_employee,
    get_employee_by_email,
    get_employee_registration,
    get_hr_report,
    get_leave_request,
    get_user_profile,
    initialize_hr_database,
    LeaveRequestOverlapError,
    list_employee_registrations,
    list_attendance,
    list_departments,
    list_employees,
    list_leave_requests,
    review_leave_request,
    reject_employee_registration,
    update_employee,
    upsert_attendance
)

from image_ocr import extract_text_from_image
from document_extractor import (
    extract_bank_card_information,
    extract_document_information,
    is_identity_card_text
)
from voice_agent import transcribe_audio

def format_extracted_information(information: dict) -> str:
    lines = []
    for key, value in information.items():
        label = key.replace("_", " ").title()
        if key == "subjects" and isinstance(value, list):
            lines.append("Subjects:")
            for index, subject in enumerate(value, start=1):
                if not isinstance(subject, dict):
                    lines.append(f"- {subject}")
                    continue
                subject_name = subject.get("subject") or f"Subject {index}"
                details = [
                    f"{field.replace('_', ' ').title()}: {field_value}"
                    for field, field_value in subject.items()
                    if field != "subject" and field_value is not None
                ]
                detail_text = f" ({'; '.join(details)})" if details else ""
                lines.append(f"- {subject_name}{detail_text}")
        elif isinstance(value, list):
            lines.append(f"{label}: {', '.join(str(item) for item in value)}")
        else:
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


# ========================================
# FASTAPI CONFIGURATION
# ========================================

api = FastAPI(
    title="AI Customer Support API",
    description="Customer support API with authentication and persistent chat history",
    version="4.0"
)

BASE_DIR = Path(__file__).resolve().parent

FRONTEND_FILE = BASE_DIR / "frontend" / "index.html"
ADMIN_FRONTEND_FILE = BASE_DIR / "frontend" / "admin.html"

initialize_hr_database()


# ========================================
# REQUEST MODELS
# ========================================

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    first_name: str | None = Field(default=None, min_length=1, max_length=80)
    last_name: str | None = Field(default=None, min_length=1, max_length=80)
    phone: str | None = Field(default=None, max_length=32)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class AdminRoleUpdateRequest(BaseModel):
    email: EmailStr
    role: Literal["employee", "hr_admin"]


class DepartmentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class EmployeeRequest(BaseModel):
    employee_code: str = Field(min_length=1, max_length=32)
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    department_id: int = Field(gt=0)
    job_title: str = Field(min_length=1, max_length=100)
    hire_date: date
    phone: str | None = Field(default=None, max_length=32)


class EmployeeRegistrationApprovalRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    employee_code: str = Field(min_length=1, max_length=32)
    department_id: int = Field(gt=0)
    job_title: str = Field(min_length=1, max_length=100)
    hire_date: date


class EmployeeRegistrationRejectionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class LeaveRequestCreate(BaseModel):
    leave_type: Literal["annual", "sick", "unpaid"]
    start_date: date
    end_date: date
    reason: str | None = Field(default=None, max_length=500)


class LeaveDecisionRequest(BaseModel):
    status: Literal["approved", "rejected"]
    review_note: str | None = Field(default=None, max_length=500)


class AttendanceRequest(BaseModel):
    employee_id: int = Field(gt=0)
    attendance_date: date
    status: Literal["present", "absent", "remote", "leave", "holiday"]
    check_in: time | None = None
    check_out: time | None = None
    note: str | None = Field(default=None, max_length=500)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=5000)
    conversation_id: str | None = None
class MemoryUpdateRequest(BaseModel):
    value: str = Field(min_length=1, max_length=200)


def employee_values(request: EmployeeRequest):
    values = {
        "employee_code": request.employee_code.strip().upper(),
        "first_name": request.first_name.strip(),
        "last_name": request.last_name.strip(),
        "email": str(request.email).strip().lower(),
        "department_id": request.department_id,
        "job_title": request.job_title.strip(),
        "hire_date": request.hire_date.isoformat(),
        "phone": request.phone.strip() if request.phone else None
    }

    required_fields = (
        "employee_code",
        "first_name",
        "last_name",
        "job_title"
    )
    if any(not values[field] for field in required_fields):
        raise HTTPException(
            status_code=422,
            detail="Employee code, name, and job title cannot be blank."
        )

    return values


# ========================================
# HOME
# ========================================

@api.get("/")
def home():

    if not FRONTEND_FILE.exists():
        raise HTTPException(
            status_code=404,
            detail="Frontend file not found"
        )

    return FileResponse(FRONTEND_FILE)


@api.get("/admin", include_in_schema=False)
def admin_home():
    if not ADMIN_FRONTEND_FILE.exists():
        raise HTTPException(
            status_code=404,
            detail="Admin dashboard file not found."
        )

    return FileResponse(ADMIN_FRONTEND_FILE)


@api.get("/leave", include_in_schema=False)
def employee_leave_home():
    leave_frontend_file = BASE_DIR / "frontend" / "leave.html"
    if not leave_frontend_file.exists():
        raise HTTPException(
            status_code=404,
            detail="Leave management page not found."
        )

    return FileResponse(leave_frontend_file)


# ========================================
# HEALTH CHECK
# ========================================

@api.get("/health")
def health():

    return {
        "status": "running",
        "message": "Customer Support API is working"
    }

def is_payment_card(text: str) -> bool:

    if is_identity_card_text(text):
        return False

    text_lower = text.lower()

    # Convert Arabic and Persian digits into English digits
    digit_translation = str.maketrans(
        "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
        "01234567890123456789"
    )

    normalized_text = text.translate(digit_translation)

    # Count all digits, even when OCR splits them across lines
    digit_count = sum(
        character.isdigit()
        for character in normalized_text
    )

    # Payment card network names
    card_networks = [
        "visa",
        "mastercard",
        "master card",
        "amex",
        "american express"
    ]

    has_card_network = any(
        network in text_lower
        for network in card_networks
    )

    # Other payment card indicators
    card_keywords = [
        "debit card",
        "credit card",
        "card number",
        "cardholder",
        "cvv",
        "cvc",
        "security code"
    ]

    keyword_matches = sum(
        1 for keyword in card_keywords
        if keyword in text_lower
    )

    # Detection rules
    if has_card_network and digit_count >= 12:
        return True

    if keyword_matches >= 2:
        return True

    if keyword_matches >= 1 and digit_count >= 12:
        return True

    return False

# ========================================
# DOCUMENT IMAGE EXTRACTION
# ========================================


@api.post("/extract-document")
def extract_document(
    file: UploadFile = File(...),
    conversation_id: str = Form(None),
    current_user: dict = Depends(get_current_user)
):

    allowed_types = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/bmp": ".bmp"
    }

    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail="Only JPG, PNG, WEBP and BMP images are allowed."
        )

    temp_path = None

    
    try:
        
        # Identify user and conversation
        user_id = current_user["id"]

        conversation_id = conversation_id or str(uuid4())

        existing_conversation = get_user_conversation(
            user_id,
            conversation_id
        )

        if not existing_conversation:
            create_conversation(
                user_id=user_id,
                conversation_id=conversation_id,
                title=f"Image: {file.filename or 'Uploaded image'}"
            )

        # Read image and enforce 5 MB limit
        image_bytes = file.file.read(5 * 1024 * 1024 + 1)

        if not image_bytes:
            raise HTTPException(
                status_code=400,
                detail="Uploaded image is empty."
            )

        if len(image_bytes) > 5 * 1024 * 1024:
            raise HTTPException(
                status_code=413,
                detail="Image size must not exceed 5 MB."
            )

        # Verify image
        try:
            image = Image.open(BytesIO(image_bytes))
            image.verify()

        except Exception:
            raise HTTPException(
                status_code=400,
                detail="Invalid or corrupted image."
            )

        # Create temporary image file
        with tempfile.NamedTemporaryFile(
            suffix=allowed_types[file.content_type],
            delete=False
        ) as temp_file:

            temp_file.write(image_bytes)
            temp_path = temp_file.name

        # Step 1: OCR
        print("\nExtracting text from uploaded image...")

        ocr_text = extract_text_from_image(temp_path)
        payment_card_detected = is_payment_card(ocr_text)

        # Step 2: Check for payment card.
        if payment_card_detected:
            print("\nSECURITY: Payment card detected!")

            result = {
                "document_type": "Bank Card",
                "extracted_information": extract_bank_card_information(
                    ocr_text
                ),
                "message": (
                    "Bank card detected. Card numbers, expiration dates, "
                    "security codes, and PINs are omitted; only safe card "
                    "details are shown."
                )
            }
        elif not ocr_text.strip():
            result = {
                "document_type": "Unknown",
                "extracted_information": {},
                "message": "No readable text found in the image."
            }
        else:
            print("\nUnderstanding uploaded document...")
            extracted_result = extract_document_information(ocr_text)
            result = {
                "message": "Document processed successfully.",
                **extracted_result
            }

        # Step 3: Prepare messages for chat history
        user_message = (
            f"Uploaded image: {file.filename or 'Uploaded image'}"
        )

        assistant_message = result["message"]

        document_type = result.get("document_type", "Unknown")

        assistant_message += (
            f"\n\nDocument type: {document_type}"
        )

        information = result.get(
            "extracted_information", {}
        )

        if information:

            assistant_message += "\n\nExtracted information:"
            assistant_message += (
                f"\n{format_extracted_information(information)}"
            )

        else:

            assistant_message += (
                "\nNo safe, readable fields were extracted."
            )

        # Step 4: Save user message
        save_message(
            conversation_id=conversation_id,
            role="user",
            content=user_message
        )

        # Step 5: Save assistant response
        save_message(
            conversation_id=conversation_id,
            role="assistant",
            content=assistant_message
        )

        print("\nImage conversation saved successfully!")

        # Return result to frontend
        return {
            **result,
            "conversation_id": conversation_id
        }

    except HTTPException:
        raise

    except Exception as e:

        print(f"Document processing error: {e}")

        raise HTTPException(
            status_code=500,
            detail="Could not process the uploaded document."
        )

    finally:

        # Delete temporary image
        if temp_path and Path(temp_path).exists():
            Path(temp_path).unlink()



# ========================================
# REGISTER
# ========================================

@api.post("/register", status_code=status.HTTP_201_CREATED)
def register(request: RegisterRequest):

    first_name = request.first_name.strip() if request.first_name else None
    last_name = request.last_name.strip() if request.last_name else None
    phone = request.phone.strip() if request.phone else None

    if (
        (request.first_name is not None and not first_name)
        or (request.last_name is not None and not last_name)
    ):
        raise HTTPException(
            status_code=422,
            detail="First and last name cannot be blank."
        )

    if bool(first_name) != bool(last_name):
        raise HTTPException(
            status_code=422,
            detail="Provide both first and last name to submit an employee profile."
        )

    if phone and not first_name:
        raise HTTPException(
            status_code=422,
            detail="A phone number can only be submitted with an employee profile."
        )

    user = create_user(
        email=request.email,
        password=request.password
    )

    registration_status = None
    if first_name and last_name:
        try:
            create_employee_registration(
                user_id=user["id"],
                email=user["email"],
                first_name=first_name,
                last_name=last_name,
                phone=phone
            )
        except sqlite3.IntegrityError as error:
            delete_user_account(user["id"])
            raise HTTPException(
                status_code=409,
                detail="An employee profile request already exists for this email."
            ) from error
        except sqlite3.Error as error:
            delete_user_account(user["id"])
            raise HTTPException(
                status_code=503,
                detail="Could not save your employee profile. No account was created."
            ) from error

        registration_status = "pending"

    return {
        "message": (
            "Account created. Your employee details are pending HR verification."
            if registration_status
            else "Account created successfully."
        ),
        "user": user,
        "employee_registration_status": registration_status
    }


# ========================================
# LOGIN
# ========================================

@api.post("/login")
def login(request: LoginRequest):

    user = authenticate_user(
        email=request.email,
        password=request.password
    )

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Incorrect email or password."
        )

    access_token = create_access_token(
        user_id=user["id"],
        email=user["email"],
        role=user["role"]
    )

    return {
        "message": "Login successful.",
        "access_token": access_token,
        "token_type": "bearer",
        "user": user
    }


# ========================================
# CURRENT USER
# ========================================

@api.get("/me")
def get_me(
    current_user: dict = Depends(get_current_user)
):

    return {
        "message": "User authenticated successfully.",
        "user": current_user,
        "profile": get_user_profile(
            user_id=current_user["id"],
            email=current_user["email"]
        )
    }


# ========================================
# ADMIN ROLE MANAGEMENT
# ========================================

@api.put("/admin/users/role")
def update_user_role(
    request: AdminRoleUpdateRequest,
    current_user: dict = Depends(require_roles("super_admin"))
):

    target_email = str(request.email).strip().lower()

    if target_email == current_user["email"]:
        raise HTTPException(
            status_code=400,
            detail="You cannot change your own role."
        )

    updated = set_user_role(
        email=target_email,
        role=request.role
    )

    if not updated:
        raise HTTPException(
            status_code=404,
            detail="User not found."
        )

    return {
        "message": "User role updated successfully.",
        "email": target_email,
        "role": request.role
    }


# ========================================
# EMPLOYEE REGISTRATION REVIEW
# ========================================

@api.get(
    "/admin/employee-registrations",
    dependencies=[Depends(
        require_roles("hr_admin", "super_admin")
    )]
)
def get_employee_registration_requests(
    status_filter: Literal["pending", "approved", "rejected", "all"] = Query(
        default="pending",
        alias="status"
    )
):
    return {
        "registrations": list_employee_registrations(status_filter)
    }


@api.post("/admin/employee-registrations/{registration_id}/approve")
def approve_employee_registration_request(
    registration_id: int,
    request: EmployeeRegistrationApprovalRequest,
    current_user: dict = Depends(
        require_roles("hr_admin", "super_admin")
    )
):
    registration = get_employee_registration(registration_id)
    if not registration:
        raise HTTPException(
            status_code=404,
            detail="Employee registration not found."
        )

    if registration["status"] != "pending":
        raise HTTPException(
            status_code=409,
            detail="This employee registration has already been reviewed."
        )

    if registration["email"].lower() == current_user["email"].lower():
        raise HTTPException(
            status_code=403,
            detail="You cannot approve your own employee registration."
        )

    if not department_exists(request.department_id):
        raise HTTPException(
            status_code=404,
            detail="Department not found."
        )

    first_name = request.first_name.strip()
    last_name = request.last_name.strip()
    employee_code = request.employee_code.strip().upper()
    job_title = request.job_title.strip()
    if not first_name or not last_name or not employee_code or not job_title:
        raise HTTPException(
            status_code=422,
            detail="Name, employee ID, and job title cannot be blank."
        )

    try:
        employee_id = approve_employee_registration(
            registration_id=registration_id,
            first_name=first_name,
            last_name=last_name,
            employee_code=employee_code,
            department_id=request.department_id,
            job_title=job_title,
            hire_date=request.hire_date.isoformat(),
            reviewer_id=current_user["id"]
        )
    except sqlite3.IntegrityError as error:
        raise HTTPException(
            status_code=409,
            detail="The employee ID or email is already in use."
        ) from error

    if not employee_id:
        raise HTTPException(
            status_code=409,
            detail="This employee registration has already been reviewed."
        )

    return {
        "registration": get_employee_registration(registration_id),
        "employee": get_employee(employee_id)
    }


@api.post("/admin/employee-registrations/{registration_id}/reject")
def reject_employee_registration_request(
    registration_id: int,
    request: EmployeeRegistrationRejectionRequest,
    current_user: dict = Depends(
        require_roles("hr_admin", "super_admin")
    )
):
    registration = get_employee_registration(registration_id)
    if not registration:
        raise HTTPException(
            status_code=404,
            detail="Employee registration not found."
        )

    if registration["status"] != "pending":
        raise HTTPException(
            status_code=409,
            detail="This employee registration has already been reviewed."
        )

    if registration["email"].lower() == current_user["email"].lower():
        raise HTTPException(
            status_code=403,
            detail="You cannot reject your own employee registration."
        )

    rejected = reject_employee_registration(
        registration_id=registration_id,
        reviewer_id=current_user["id"],
        rejection_note=request.reason.strip() if request.reason else None
    )
    if not rejected:
        raise HTTPException(
            status_code=409,
            detail="This employee registration has already been reviewed."
        )

    return {
        "registration": get_employee_registration(registration_id)
    }


# ========================================
# EMPLOYEE AND DEPARTMENT MANAGEMENT
# ========================================

@api.get(
    "/admin/dashboard/stats",
    dependencies=[Depends(
        require_roles("hr_admin", "super_admin")
    )]
)
def admin_dashboard_stats():
    return get_dashboard_stats()


@api.get(
    "/admin/departments",
    dependencies=[Depends(
        require_roles("hr_admin", "super_admin")
    )]
)
def get_departments():
    return {"departments": list_departments()}


@api.post(
    "/admin/departments",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(
        require_roles("hr_admin", "super_admin")
    )]
)
def add_department(
    request: DepartmentCreateRequest
):
    name = request.name.strip()
    if not name:
        raise HTTPException(
            status_code=422,
            detail="Department name cannot be blank."
        )

    try:
        department_id = create_department(name)
    except sqlite3.IntegrityError as error:
        raise HTTPException(
            status_code=409,
            detail="A department with this name already exists."
        ) from error

    return {
        "department": {
            "id": department_id,
            "name": name,
            "employee_count": 0
        }
    }


@api.get(
    "/admin/employees",
    dependencies=[Depends(
        require_roles("hr_admin", "super_admin")
    )]
)
def get_employees(
    search: str = Query(default="", max_length=100),
    department_id: int | None = Query(default=None, gt=0),
    status_filter: Literal["active", "inactive", "all"] = Query(
        default="active",
        alias="status"
    )
):
    return {
        "employees": list_employees(
            search=search,
            department_id=department_id,
            status_filter=status_filter
        )
    }


@api.post(
    "/admin/employees",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(
        require_roles("hr_admin", "super_admin")
    )]
)
def add_employee(
    request: EmployeeRequest
):
    values = employee_values(request)
    if not department_exists(values["department_id"]):
        raise HTTPException(
            status_code=404,
            detail="Department not found."
        )

    try:
        employee_id = create_employee(values)
    except sqlite3.IntegrityError as error:
        raise HTTPException(
            status_code=409,
            detail="An employee with this email or code already exists."
        ) from error

    return {"employee": get_employee(employee_id)}


@api.put(
    "/admin/employees/{employee_id}",
    dependencies=[Depends(
        require_roles("hr_admin", "super_admin")
    )]
)
def edit_employee(
    employee_id: int,
    request: EmployeeRequest
):
    values = employee_values(request)
    if not department_exists(values["department_id"]):
        raise HTTPException(
            status_code=404,
            detail="Department not found."
        )

    try:
        updated = update_employee(employee_id, values)
    except sqlite3.IntegrityError as error:
        raise HTTPException(
            status_code=409,
            detail="An employee with this email or code already exists."
        ) from error

    if not updated:
        raise HTTPException(
            status_code=404,
            detail="Employee not found."
        )

    return {"employee": get_employee(employee_id)}


@api.patch(
    "/admin/employees/{employee_id}/deactivate",
    dependencies=[Depends(
        require_roles("hr_admin", "super_admin")
    )]
)
def deactivate_employee_record(
    employee_id: int
):
    if not deactivate_employee(employee_id):
        raise HTTPException(
            status_code=404,
            detail="Employee not found."
        )

    return {"employee": get_employee(employee_id)}


# ========================================
# LEAVE, ATTENDANCE, AND REPORTS
# ========================================

@api.get("/leave-requests")
def get_leave_requests(
    status_filter: Literal["all", "pending", "approved", "rejected"] = Query(
        default="all",
        alias="status"
    ),
    current_user: dict = Depends(get_current_user)
):
    if current_user["role"] == "employee":
        employee = get_employee_by_email(current_user["email"])
        if not employee:
            return {"leave_requests": []}
        return {
            "leave_requests": list_leave_requests(
                employee_id=employee["id"],
                status_filter=status_filter
            )
        }

    return {
        "leave_requests": list_leave_requests(
            status_filter=status_filter
        )
    }


@api.post("/leave-requests", status_code=status.HTTP_201_CREATED)
def add_leave_request(
    request: LeaveRequestCreate,
    current_user: dict = Depends(get_current_user)
):
    if request.end_date < request.start_date:
        raise HTTPException(
            status_code=422,
            detail="Leave end date cannot be before its start date."
        )

    employee = get_employee_by_email(current_user["email"])
    if not employee:
        raise HTTPException(
            status_code=404,
            detail="No active employee record is linked to this account."
        )

    try:
        request_id = create_leave_request(
            employee_id=employee["id"],
            leave_type=request.leave_type,
            start_date=request.start_date.isoformat(),
            end_date=request.end_date.isoformat(),
            reason=request.reason.strip() if request.reason else None
        )
    except LeaveRequestOverlapError as error:
        raise HTTPException(
            status_code=409,
            detail="This leave period overlaps a pending or approved request."
        ) from error

    return {"leave_request": get_leave_request(request_id)}


@api.patch("/admin/leave-requests/{request_id}/decision")
def decide_leave_request(
    request_id: int,
    request: LeaveDecisionRequest,
    current_user: dict = Depends(
        require_roles("hr_admin", "super_admin")
    )
):
    leave_request = get_leave_request(request_id)
    if not leave_request:
        raise HTTPException(
            status_code=404,
            detail="Leave request not found."
        )

    if leave_request["email"].lower() == current_user["email"].lower():
        raise HTTPException(
            status_code=403,
            detail="You cannot approve or reject your own leave request."
        )

    reviewed = review_leave_request(
        request_id=request_id,
        status=request.status,
        reviewer_id=current_user["id"],
        review_note=request.review_note.strip() if request.review_note else None
    )
    if not reviewed:
        raise HTTPException(
            status_code=409,
            detail="This leave request has already been reviewed."
        )

    return {"leave_request": get_leave_request(request_id)}


@api.get(
    "/admin/attendance",
    dependencies=[Depends(
        require_roles("hr_admin", "super_admin")
    )]
)
def get_attendance_records(
    attendance_date: date | None = Query(default=None, alias="date"),
    employee_id: int | None = Query(default=None, gt=0)
):
    return {
        "attendance": list_attendance(
            attendance_date=(
                attendance_date.isoformat()
                if attendance_date
                else None
            ),
            employee_id=employee_id
        )
    }


@api.put(
    "/admin/attendance"
)
def record_attendance(
    request: AttendanceRequest,
    current_user: dict = Depends(
        require_roles("hr_admin", "super_admin")
    )
):
    if (
        request.check_in
        and request.check_out
        and request.check_out <= request.check_in
    ):
        raise HTTPException(
            status_code=422,
            detail="Check-out time must be after check-in time."
        )

    if not get_employee(request.employee_id):
        raise HTTPException(
            status_code=404,
            detail="Employee not found."
        )

    record = {
        "employee_id": request.employee_id,
        "attendance_date": request.attendance_date.isoformat(),
        "status": request.status,
        "check_in": request.check_in.isoformat() if request.check_in else None,
        "check_out": request.check_out.isoformat() if request.check_out else None,
        "note": request.note.strip() if request.note else None
    }

    return {
        "attendance": upsert_attendance(
            record,
            recorded_by=current_user["id"]
        )
    }


@api.get(
    "/admin/reports/summary",
    dependencies=[Depends(
        require_roles("hr_admin", "super_admin")
    )]
)
def get_admin_report(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None)
):
    start_date = start_date or date.today().replace(day=1)
    end_date = end_date or date.today()

    if end_date < start_date:
        raise HTTPException(
            status_code=422,
            detail="Report end date cannot be before its start date."
        )

    return get_hr_report(
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat()
    )


# ========================================
# CHAT
# ========================================

def get_uploaded_document_context(messages: list[dict]) -> str:
    document_messages = [
        message["content"]
        for message in messages
        if (
            message.get("role") == "assistant"
            and "Document type:" in message.get("content", "")
            and "Extracted information:" in message.get("content", "")
        )
    ]
    return "\n\n".join(reversed(document_messages[-3:]))


def answer_profile_question(
    message: str,
    profile: dict,
    document_context: str = ""
):
    normalized_message = message.casefold().strip()
    asks_question = (
        "?" in normalized_message
        or normalized_message.startswith((
            "what ",
            "what's ",
            "whats ",
            "who ",
            "who's ",
            "tell me ",
            "show me ",
            "do you know ",
            "can you tell me "
        ))
    )
    asks_about_user = any(phrase in normalized_message for phrase in (
        "my name",
        "my email",
        "my phone",
        "my profile",
        "who am i",
        "about me"
    ))

    if not asks_question or not asks_about_user:
        return None

    if "name" in normalized_message and document_context:
        document_name = re.search(
            r"(?im)^\s*(?:student\s+name|full\s+name|name)\s*:\s*"
            r"([^\r\n;]+)",
            document_context
        )
        if document_name:
            return (
                "The name shown on the uploaded document is "
                f"{document_name.group(1).strip()}."
            )

    name = " ".join(
        part for part in (profile["first_name"], profile["last_name"])
        if part
    ) or "Not provided"
    email = profile["email"]
    phone = profile["phone"] or "Not provided"

    if "profile" in normalized_message or "about me" in normalized_message:
        return (
            f"Your profile: Name: {name}; Email: {email}; "
            f"Phone: {phone}."
        )
    if "email" in normalized_message:
        return f"Your email address is {email}."
    if "phone" in normalized_message:
        return f"Your phone number is {phone}."
    return f"Your name is {name}."


@api.post("/chat")
def chat(
    request: ChatRequest,
    current_user: dict = Depends(get_current_user)
):

    user_message = request.message.strip()

    if not user_message:
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty"
        )

    # Get authenticated customer ID
    user_id = current_user["id"]

    # Use existing conversation ID or create a new one
    conversation_id = (
        request.conversation_id or str(uuid4())
    )

    if len(conversation_id) > 100:
        raise HTTPException(
            status_code=400,
            detail="Invalid conversation ID"
        )

    # Check whether this conversation belongs to the user
    conversation = get_user_conversation(
        user_id,
        conversation_id
    )

    # Create conversation if it does not exist
    if not conversation:

        try:

            create_conversation(
                user_id=user_id,
                conversation_id=conversation_id,
                title=user_message
            )

        except sqlite3.IntegrityError:

            raise HTTPException(
                status_code=409,
                detail="This conversation ID is already in use."
            )

    # Save customer message
    save_message(
        conversation_id=conversation_id,
        role="user",
        content=user_message
    )

    profile = get_user_profile(
        user_id=user_id,
        email=current_user["email"]
    )
    conversation_messages = get_conversation_messages(
        user_id,
        conversation_id
    ) or []
    document_context = get_uploaded_document_context(conversation_messages)
    profile_response = answer_profile_question(
        user_message,
        profile,
        document_context
    )
    if profile_response:
        save_message(
            conversation_id=conversation_id,
            role="assistant",
            content=profile_response,
            category="Account"
        )
        return {
            "conversation_id": conversation_id,
            "category": "Account",
            "response": profile_response
        }

    employee_context = get_chat_employee_context(
        email=current_user["email"],
        role=current_user["role"],
        message=user_message
    )

    # Create user-specific LangGraph thread
    if current_user["role"] == "employee":
        thread_id = f"user:{user_id}:conversation:{conversation_id}"
    else:
        thread_id = (
            f"user:{user_id}:role:{current_user['role']}:"
            f"conversation:{conversation_id}"
        )

    
    initial_state = {
    "message": user_message,

    "user_id": user_id,

    "category": "",

    "context": "",

    "user_memories": "",

    "employee_context": employee_context,

    "document_context": document_context,

    "response": "",

    # Current user message
    "chat_history": [
        {
            "role": "user",
            "content": user_message
        }
    ]
}
    config = {
        "configurable": {
            "thread_id": thread_id
        }
    }

    try:

        # Execute LangGraph
        result = graph_app.invoke(
            initial_state,
            config=config
        )

        ai_response = result.get(
            "response",
            "No response generated."
        )

        category = result.get(
            "category",
            "General"
        )

        # Save AI response
        save_message(
            conversation_id=conversation_id,
            role="assistant",
            content=ai_response,
            category=category
        )

        return {

            "conversation_id": conversation_id,

            "category": category,

            "response": ai_response

        }

    except Exception as e:

        print(f"API Error: {e}")

        raise HTTPException(
            status_code=500,
            detail="Something went wrong while processing your message."
        )


@api.post("/voice-chat")
async def voice_chat(
    file: UploadFile = File(...),
    conversation_id: str = Form(None),
    current_user: dict = Depends(get_current_user)
):
    import os
    import tempfile

    # Validate audio file type
    allowed_types = [
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/mp4",
    "audio/m4a",
    "audio/ogg",
    "audio/webm",
    "audio/webm;codecs=opus",
    "audio/flac"
]

    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail="Unsupported audio format."
        )

    # Read audio file
    audio_data = await file.read()

    if not audio_data:
        raise HTTPException(
            status_code=400,
            detail="Audio file is empty."
        )

    # Limit audio size to 20 MB
    if len(audio_data) > 20 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="Audio file must be smaller than 20 MB."
        )

    # Save temporarily
    suffix = os.path.splitext(file.filename or "voice.webm")[1]

    if not suffix:
        suffix = ".webm"

    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix
        ) as temp_file:

            temp_file.write(audio_data)
            temp_path = temp_file.name

        # Convert voice to text
        transcribed_text = transcribe_audio(temp_path)

        if not transcribed_text or not transcribed_text.strip():
            raise HTTPException(
                status_code=400,
                detail="No speech could be detected."
            )

        # Reuse the existing chatbot endpoint
        chat_request = ChatRequest(
            message=transcribed_text.strip(),
            conversation_id=conversation_id
        )

        result = chat(
            request=chat_request,
            current_user=current_user
        )

        return {
            "conversation_id": result["conversation_id"],
            "transcribed_text": transcribed_text.strip(),
            "category": result["category"],
            "response": result["response"]
        }

    except HTTPException:
        raise

    except Exception as e:
        print(f"Voice API Error: {e}")

        raise HTTPException(
            status_code=500,
            detail="Could not process your voice message."
        )

    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

# ========================================
# GET ALL USER CONVERSATIONS
# ========================================

@api.get("/conversations")
def list_conversations(
    current_user: dict = Depends(get_current_user)
):

    conversations = get_user_conversations(
        current_user["id"]
    )

    return {
        "conversations": conversations
    }


# ========================================
# GET MESSAGES FROM A CONVERSATION
# ========================================

@api.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user)
):

    messages = get_conversation_messages(
        current_user["id"],
        conversation_id
    )

    if messages is None:

        raise HTTPException(
            status_code=404,
            detail="Conversation not found."
        )

    conversation = get_user_conversation(
        current_user["id"],
        conversation_id
    )

    return {
        "conversation": conversation,
        "messages": messages
    }


# ========================================
# DELETE A CONVERSATION
# ========================================

@api.delete("/conversations/{conversation_id}")
def remove_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user)
):

    deleted = delete_conversation(
        current_user["id"],
        conversation_id
    )

    if not deleted:

        raise HTTPException(
            status_code=404,
            detail="Conversation not found."
        )

    return {
        "message": "Conversation deleted successfully.",
        "conversation_id": conversation_id
    }

# ========================================
# USER MEMORY MANAGEMENT
# ========================================

ALLOWED_MEMORY_KEYS = {
    "name",
    "preferred_language",
    "job_role",
    "interests",
    "leave_balance",
    "department",
    "notification_preference"
}


# VIEW ALL SAVED MEMORIES
@api.get("/memories")
def list_memories(
    current_user: dict = Depends(get_current_user)
):

    memories = fetch_user_memories(current_user["id"])

    return {
        "memories": memories
    }


# UPDATE OR CREATE A MEMORY
@api.put("/memories/{memory_key}")
def update_memory(
    memory_key: str,
    request: MemoryUpdateRequest,
    current_user: dict = Depends(get_current_user)
):

    memory_key = memory_key.strip().lower()
    memory_value = request.value.strip()

    if memory_key not in ALLOWED_MEMORY_KEYS:
        raise HTTPException(
            status_code=400,
            detail="Invalid memory category."
        )

    if not memory_value:
        raise HTTPException(
            status_code=400,
            detail="Memory value cannot be empty."
        )

    save_user_memory(
        current_user["id"],
        memory_key,
        memory_value
    )

    return {
        "message": "Memory saved successfully.",
        "memory_key": memory_key,
        "memory_value": memory_value
    }


# DELETE ONE MEMORY
@api.delete("/memories/{memory_key}")
def remove_memory(
    memory_key: str,
    current_user: dict = Depends(get_current_user)
):

    memory_key = memory_key.strip().lower()

    if memory_key not in ALLOWED_MEMORY_KEYS:
        raise HTTPException(
            status_code=400,
            detail="Invalid memory category."
        )

    deleted = delete_user_memory(
        current_user["id"],
        memory_key
    )

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Memory not found."
        )

    return {
        "message": "Memory deleted successfully.",
        "memory_key": memory_key
    }


# DELETE ALL MEMORIES
@api.delete("/memories")
def remove_all_memories(
    current_user: dict = Depends(get_current_user)
):

    deleted_count = delete_all_user_memories(
        current_user["id"]
    )

    return {
        "message": "All memories deleted successfully.",
        "deleted_count": deleted_count
    }
