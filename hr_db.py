import sqlite3
from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "employees.db"


class LeaveRequestOverlapError(Exception):
    pass


def get_hr_db_connection():
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_hr_database():
    connection = get_hr_db_connection()

    try:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS departments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                created_at TEXT NOT NULL
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_code TEXT NOT NULL COLLATE NOCASE UNIQUE,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                department_id INTEGER NOT NULL,
                job_title TEXT NOT NULL,
                hire_date TEXT NOT NULL,
                phone TEXT,
                is_active INTEGER NOT NULL DEFAULT 1
                    CHECK (is_active IN (0, 1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (department_id)
                    REFERENCES departments(id)
                    ON DELETE RESTRICT
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS leave_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                leave_type TEXT NOT NULL
                    CHECK (leave_type IN ('annual', 'sick', 'unpaid')),
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                reason TEXT,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected')),
                review_note TEXT,
                reviewed_by INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK (end_date >= start_date),
                FOREIGN KEY (employee_id)
                    REFERENCES employees(id)
                    ON DELETE RESTRICT
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS employee_registrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                phone TEXT,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected')),
                employee_id INTEGER UNIQUE,
                rejection_note TEXT,
                submitted_at TEXT NOT NULL,
                resolved_at TEXT,
                resolved_by INTEGER,
                FOREIGN KEY (employee_id)
                    REFERENCES employees(id)
                    ON DELETE RESTRICT
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                attendance_date TEXT NOT NULL,
                status TEXT NOT NULL
                    CHECK (status IN ('present', 'absent', 'remote', 'leave', 'holiday')),
                check_in TEXT,
                check_out TEXT,
                note TEXT,
                recorded_by INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(employee_id, attendance_date),
                FOREIGN KEY (employee_id)
                    REFERENCES employees(id)
                    ON DELETE RESTRICT
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_employees_department
            ON employees(department_id)
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_employees_name
            ON employees(last_name, first_name)
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_employees_active
            ON employees(is_active)
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_leave_requests_employee
            ON leave_requests(employee_id, status)
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_employee_registrations_status
            ON employee_registrations(status, submitted_at)
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_attendance_date
            ON attendance(attendance_date, employee_id)
        """)

        connection.commit()

    finally:
        connection.close()


def create_department(name: str):
    connection = get_hr_db_connection()

    try:
        cursor = connection.execute(
            "INSERT INTO departments (name, created_at) VALUES (?, ?)",
            (name, datetime.now(timezone.utc).isoformat())
        )
        connection.commit()
        return cursor.lastrowid

    finally:
        connection.close()


def list_departments():
    connection = get_hr_db_connection()

    try:
        departments = connection.execute("""
            SELECT d.id, d.name, COUNT(e.id) AS employee_count
            FROM departments AS d
            LEFT JOIN employees AS e ON e.department_id = d.id
            GROUP BY d.id, d.name
            ORDER BY d.name COLLATE NOCASE
        """).fetchall()
        return [dict(department) for department in departments]

    finally:
        connection.close()


def department_exists(department_id: int):
    connection = get_hr_db_connection()

    try:
        department = connection.execute(
            "SELECT 1 FROM departments WHERE id = ?",
            (department_id,)
        ).fetchone()
        return department is not None

    finally:
        connection.close()


def create_employee_registration(
    user_id: int,
    email: str,
    first_name: str,
    last_name: str,
    phone: str | None
):
    connection = get_hr_db_connection()

    try:
        cursor = connection.execute("""
            INSERT INTO employee_registrations (
                user_id,
                email,
                first_name,
                last_name,
                phone,
                submitted_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            email.strip().lower(),
            first_name.strip(),
            last_name.strip(),
            phone.strip() if phone else None,
            datetime.now(timezone.utc).isoformat()
        ))
        connection.commit()
        return cursor.lastrowid

    finally:
        connection.close()


def list_employee_registrations(status_filter: str = "pending"):
    if status_filter not in {"pending", "approved", "rejected", "all"}:
        raise ValueError("Invalid employee registration status filter.")

    where_clause = "" if status_filter == "all" else "WHERE r.status = ?"
    parameters = () if status_filter == "all" else (status_filter,)
    connection = get_hr_db_connection()

    try:
        registrations = connection.execute(f"""
            SELECT
                r.id,
                r.user_id,
                r.email,
                r.first_name,
                r.last_name,
                r.phone,
                r.status,
                r.employee_id,
                r.rejection_note,
                r.submitted_at,
                r.resolved_at,
                r.resolved_by
            FROM employee_registrations AS r
            {where_clause}
            ORDER BY
                CASE r.status WHEN 'pending' THEN 0 ELSE 1 END,
                r.submitted_at DESC
        """, parameters).fetchall()
        return [dict(registration) for registration in registrations]

    finally:
        connection.close()


def get_employee_registration(registration_id: int):
    connection = get_hr_db_connection()

    try:
        registration = connection.execute("""
            SELECT
                id,
                user_id,
                email,
                first_name,
                last_name,
                phone,
                status,
                employee_id,
                rejection_note,
                submitted_at,
                resolved_at,
                resolved_by
            FROM employee_registrations
            WHERE id = ?
        """, (registration_id,)).fetchone()
        return dict(registration) if registration else None

    finally:
        connection.close()


def is_employee_registration_rejected(user_id: int):
    connection = get_hr_db_connection()

    try:
        registration = connection.execute("""
            SELECT status
            FROM employee_registrations
            WHERE user_id = ?
        """, (user_id,)).fetchone()
        return registration is not None and registration["status"] == "rejected"

    finally:
        connection.close()


def approve_employee_registration(
    registration_id: int,
    first_name: str,
    last_name: str,
    employee_code: str,
    department_id: int,
    job_title: str,
    hire_date: str,
    reviewer_id: int
):
    now = datetime.now(timezone.utc).isoformat()
    connection = get_hr_db_connection()

    try:
        connection.execute("BEGIN IMMEDIATE")
        registration = connection.execute("""
            SELECT email, first_name, last_name, phone, status
            FROM employee_registrations
            WHERE id = ?
        """, (registration_id,)).fetchone()

        if not registration or registration["status"] != "pending":
            return None

        cursor = connection.execute("""
            INSERT INTO employees (
                employee_code,
                first_name,
                last_name,
                email,
                department_id,
                job_title,
                hire_date,
                phone,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            employee_code,
            first_name,
            last_name,
            registration["email"],
            department_id,
            job_title,
            hire_date,
            registration["phone"],
            now,
            now
        ))
        employee_id = cursor.lastrowid

        connection.execute("""
            UPDATE employee_registrations
            SET
                status = 'approved',
                employee_id = ?,
                resolved_at = ?,
                resolved_by = ?,
                rejection_note = NULL
            WHERE id = ? AND status = 'pending'
        """, (
            employee_id,
            now,
            reviewer_id,
            registration_id
        ))
        connection.commit()
        return employee_id

    finally:
        connection.close()


def reject_employee_registration(
    registration_id: int,
    reviewer_id: int,
    rejection_note: str | None
):
    now = datetime.now(timezone.utc).isoformat()
    connection = get_hr_db_connection()

    try:
        cursor = connection.execute("""
            UPDATE employee_registrations
            SET
                status = 'rejected',
                rejection_note = ?,
                resolved_at = ?,
                resolved_by = ?
            WHERE id = ? AND status = 'pending'
        """, (
            rejection_note,
            now,
            reviewer_id,
            registration_id
        ))
        connection.commit()
        return cursor.rowcount > 0

    finally:
        connection.close()


def create_employee(employee: dict):
    now = datetime.now(timezone.utc).isoformat()
    connection = get_hr_db_connection()

    try:
        cursor = connection.execute("""
            INSERT INTO employees (
                employee_code,
                first_name,
                last_name,
                email,
                department_id,
                job_title,
                hire_date,
                phone,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            employee["employee_code"],
            employee["first_name"],
            employee["last_name"],
            employee["email"],
            employee["department_id"],
            employee["job_title"],
            employee["hire_date"],
            employee["phone"],
            now,
            now
        ))
        connection.commit()
        return cursor.lastrowid

    finally:
        connection.close()


def get_employee(employee_id: int):
    connection = get_hr_db_connection()

    try:
        employee = connection.execute("""
            SELECT
                e.id,
                e.employee_code,
                e.first_name,
                e.last_name,
                e.email,
                e.department_id,
                d.name AS department_name,
                e.job_title,
                e.hire_date,
                e.phone,
                e.is_active,
                e.created_at,
                e.updated_at
            FROM employees AS e
            JOIN departments AS d ON d.id = e.department_id
            WHERE e.id = ?
        """, (employee_id,)).fetchone()
        return dict(employee) if employee else None

    finally:
        connection.close()


def get_employee_by_email(email: str, active_only: bool = True):
    conditions = ["lower(e.email) = ?"]
    parameters = [email.strip().lower()]
    if active_only:
        conditions.append("e.is_active = 1")

    connection = get_hr_db_connection()

    try:
        employee = connection.execute(f"""
            SELECT
                e.id,
                e.employee_code,
                e.first_name,
                e.last_name,
                e.email,
                e.department_id,
                d.name AS department_name,
                e.job_title,
                e.hire_date,
                e.phone,
                e.is_active
            FROM employees AS e
            JOIN departments AS d ON d.id = e.department_id
            WHERE {' AND '.join(conditions)}
        """, parameters).fetchone()
        return dict(employee) if employee else None

    finally:
        connection.close()


def get_user_profile(user_id: int, email: str):
    connection = get_hr_db_connection()

    try:
        employee = connection.execute("""
            SELECT first_name, last_name, email, phone, is_active
            FROM employees
            WHERE lower(email) = ?
        """, (email.strip().lower(),)).fetchone()

        if employee:
            profile = dict(employee)
            profile["status"] = "verified" if profile.pop("is_active") else "inactive"
            return profile

        registration = connection.execute("""
            SELECT first_name, last_name, email, phone, status
            FROM employee_registrations
            WHERE user_id = ?
        """, (user_id,)).fetchone()

        if registration:
            return dict(registration)

        return {
            "first_name": None,
            "last_name": None,
            "email": email,
            "phone": None,
            "status": "not_submitted"
        }

    finally:
        connection.close()


def list_employees(
    search: str = "",
    department_id: int | None = None,
    status_filter: str = "active"
):
    if status_filter not in {"active", "inactive", "all"}:
        raise ValueError("Invalid employee status filter.")

    conditions = []
    parameters = []

    if status_filter != "all":
        conditions.append("e.is_active = ?")
        parameters.append(1 if status_filter == "active" else 0)

    if department_id is not None:
        conditions.append("e.department_id = ?")
        parameters.append(department_id)

    search = search.strip()
    if search:
        conditions.append("""
            (
                e.employee_code LIKE ?
                OR e.first_name LIKE ?
                OR e.last_name LIKE ?
                OR e.email LIKE ?
                OR e.job_title LIKE ?
            )
        """)
        search_pattern = f"%{search}%"
        parameters.extend([search_pattern] * 5)

    where_clause = (
        f"WHERE {' AND '.join(conditions)}"
        if conditions
        else ""
    )
    connection = get_hr_db_connection()

    try:
        employees = connection.execute(f"""
            SELECT
                e.id,
                e.employee_code,
                e.first_name,
                e.last_name,
                e.email,
                e.department_id,
                d.name AS department_name,
                e.job_title,
                e.hire_date,
                e.phone,
                e.is_active,
                e.created_at,
                e.updated_at
            FROM employees AS e
            JOIN departments AS d ON d.id = e.department_id
            {where_clause}
            ORDER BY e.last_name COLLATE NOCASE, e.first_name COLLATE NOCASE
        """, parameters).fetchall()
        return [dict(employee) for employee in employees]

    finally:
        connection.close()


def create_leave_request(
    employee_id: int,
    leave_type: str,
    start_date: str,
    end_date: str,
    reason: str | None
):
    now = datetime.now(timezone.utc).isoformat()
    connection = get_hr_db_connection()

    try:
        connection.execute("BEGIN IMMEDIATE")
        overlapping = connection.execute("""
            SELECT 1
            FROM leave_requests
            WHERE employee_id = ?
                AND status IN ('pending', 'approved')
                AND start_date <= ?
                AND end_date >= ?
        """, (employee_id, end_date, start_date)).fetchone()
        if overlapping:
            raise LeaveRequestOverlapError

        cursor = connection.execute("""
            INSERT INTO leave_requests (
                employee_id,
                leave_type,
                start_date,
                end_date,
                reason,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            employee_id,
            leave_type,
            start_date,
            end_date,
            reason,
            now,
            now
        ))
        connection.commit()
        return cursor.lastrowid

    finally:
        connection.close()


def list_leave_requests(
    employee_id: int | None = None,
    status_filter: str = "all"
):
    if status_filter not in {"all", "pending", "approved", "rejected"}:
        raise ValueError("Invalid leave request status filter.")

    conditions = []
    parameters = []
    if employee_id is not None:
        conditions.append("l.employee_id = ?")
        parameters.append(employee_id)
    if status_filter != "all":
        conditions.append("l.status = ?")
        parameters.append(status_filter)

    where_clause = (
        f"WHERE {' AND '.join(conditions)}"
        if conditions
        else ""
    )
    connection = get_hr_db_connection()

    try:
        requests = connection.execute(f"""
            SELECT
                l.id,
                l.employee_id,
                e.employee_code,
                e.first_name,
                e.last_name,
                e.email,
                l.leave_type,
                l.start_date,
                l.end_date,
                l.reason,
                l.status,
                l.review_note,
                l.reviewed_by,
                l.created_at,
                l.updated_at
            FROM leave_requests AS l
            JOIN employees AS e ON e.id = l.employee_id
            {where_clause}
            ORDER BY
                CASE l.status WHEN 'pending' THEN 0 ELSE 1 END,
                l.created_at DESC
        """, parameters).fetchall()
        return [dict(request) for request in requests]

    finally:
        connection.close()


def get_leave_request(request_id: int):
    connection = get_hr_db_connection()

    try:
        request = connection.execute("""
            SELECT
                l.id,
                l.employee_id,
                e.employee_code,
                e.first_name,
                e.last_name,
                e.email,
                l.leave_type,
                l.start_date,
                l.end_date,
                l.reason,
                l.status,
                l.review_note,
                l.reviewed_by,
                l.created_at,
                l.updated_at
            FROM leave_requests AS l
            JOIN employees AS e ON e.id = l.employee_id
            WHERE l.id = ?
        """, (request_id,)).fetchone()
        return dict(request) if request else None

    finally:
        connection.close()


def review_leave_request(
    request_id: int,
    status: str,
    reviewer_id: int,
    review_note: str | None
):
    if status not in {"approved", "rejected"}:
        raise ValueError("Invalid leave decision.")

    connection = get_hr_db_connection()

    try:
        cursor = connection.execute("""
            UPDATE leave_requests
            SET
                status = ?,
                review_note = ?,
                reviewed_by = ?,
                updated_at = ?
            WHERE id = ? AND status = 'pending'
        """, (
            status,
            review_note,
            reviewer_id,
            datetime.now(timezone.utc).isoformat(),
            request_id
        ))
        connection.commit()
        return cursor.rowcount > 0

    finally:
        connection.close()


def upsert_attendance(record: dict, recorded_by: int):
    now = datetime.now(timezone.utc).isoformat()
    connection = get_hr_db_connection()

    try:
        connection.execute("""
            INSERT INTO attendance (
                employee_id,
                attendance_date,
                status,
                check_in,
                check_out,
                note,
                recorded_by,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(employee_id, attendance_date)
            DO UPDATE SET
                status = excluded.status,
                check_in = excluded.check_in,
                check_out = excluded.check_out,
                note = excluded.note,
                recorded_by = excluded.recorded_by,
                updated_at = excluded.updated_at
        """, (
            record["employee_id"],
            record["attendance_date"],
            record["status"],
            record["check_in"],
            record["check_out"],
            record["note"],
            recorded_by,
            now,
            now
        ))
        connection.commit()
        attendance = connection.execute("""
            SELECT
                a.id,
                a.employee_id,
                e.employee_code,
                e.first_name,
                e.last_name,
                a.attendance_date,
                a.status,
                a.check_in,
                a.check_out,
                a.note,
                a.recorded_by,
                a.updated_at
            FROM attendance AS a
            JOIN employees AS e ON e.id = a.employee_id
            WHERE a.employee_id = ? AND a.attendance_date = ?
        """, (
            record["employee_id"],
            record["attendance_date"]
        )).fetchone()
        return dict(attendance)

    finally:
        connection.close()


def list_attendance(
    attendance_date: str | None = None,
    employee_id: int | None = None
):
    conditions = []
    parameters = []
    if attendance_date is not None:
        conditions.append("a.attendance_date = ?")
        parameters.append(attendance_date)
    if employee_id is not None:
        conditions.append("a.employee_id = ?")
        parameters.append(employee_id)

    where_clause = (
        f"WHERE {' AND '.join(conditions)}"
        if conditions
        else ""
    )
    connection = get_hr_db_connection()

    try:
        records = connection.execute(f"""
            SELECT
                a.id,
                a.employee_id,
                e.employee_code,
                e.first_name,
                e.last_name,
                a.attendance_date,
                a.status,
                a.check_in,
                a.check_out,
                a.note,
                a.recorded_by,
                a.updated_at
            FROM attendance AS a
            JOIN employees AS e ON e.id = a.employee_id
            {where_clause}
            ORDER BY a.attendance_date DESC, e.last_name COLLATE NOCASE
        """, parameters).fetchall()
        return [dict(record) for record in records]

    finally:
        connection.close()


def get_hr_report(start_date: str, end_date: str):
    connection = get_hr_db_connection()

    try:
        leave_counts = connection.execute("""
            SELECT status, COUNT(*) AS count
            FROM leave_requests
            WHERE start_date <= ? AND end_date >= ?
            GROUP BY status
        """, (end_date, start_date)).fetchall()
        attendance_counts = connection.execute("""
            SELECT status, COUNT(*) AS count
            FROM attendance
            WHERE attendance_date BETWEEN ? AND ?
            GROUP BY status
        """, (start_date, end_date)).fetchall()
        department_counts = connection.execute("""
            SELECT d.name, COUNT(e.id) AS employee_count
            FROM departments AS d
            LEFT JOIN employees AS e
                ON e.department_id = d.id AND e.is_active = 1
            GROUP BY d.id, d.name
            ORDER BY d.name COLLATE NOCASE
        """).fetchall()

        return {
            "start_date": start_date,
            "end_date": end_date,
            "leave_by_status": {
                row["status"]: row["count"] for row in leave_counts
            },
            "attendance_by_status": {
                row["status"]: row["count"] for row in attendance_counts
            },
            "active_employees_by_department": [
                dict(row) for row in department_counts
            ]
        }

    finally:
        connection.close()


def get_chat_employee_records(email: str, role: str, message: str):
    if role == "employee":
        message = message.lower()
        employee_terms = (
            "my ",
            "employee",
            "profile",
            "department",
            "job title",
            "hire date",
            "leave",
            "vacation",
            "time off",
            "attendance",
            "clock",
            "timesheet"
        )
        if not any(term in message for term in employee_terms):
            return []

        employee = get_employee_by_email(email, active_only=False)
        if not employee:
            return []

        connection = get_hr_db_connection()
        try:
            coworker = connection.execute("""
                SELECT 1
                FROM employees
                WHERE lower(email) != ?
                    AND (
                        (
                            length(employee_code) >= 3
                            AND instr(?, lower(employee_code)) > 0
                        )
                        OR instr(?, lower(email)) > 0
                        OR instr(
                            ?,
                            lower(first_name || ' ' || last_name)
                        ) > 0
                    )
                LIMIT 1
            """, (
                email.strip().lower(),
                message,
                message,
                message
            )).fetchone()
            if coworker:
                return []
        finally:
            connection.close()

        return [employee] if employee else []

    if role not in {"hr_admin", "super_admin"}:
        return []

    query = message.strip().lower()
    if len(query) < 3:
        return []

    connection = get_hr_db_connection()

    try:
        matches = connection.execute("""
            SELECT
                e.id,
                e.employee_code,
                e.first_name,
                e.last_name,
                e.email,
                d.name AS department_name,
                e.job_title,
                e.hire_date,
                e.is_active
            FROM employees AS e
            JOIN departments AS d ON d.id = e.department_id
            WHERE
                (
                    length(e.employee_code) >= 3
                    AND instr(?, lower(e.employee_code)) > 0
                )
                OR instr(?, lower(e.email)) > 0
                OR instr(?, lower(e.first_name || ' ' || e.last_name)) > 0
            ORDER BY e.last_name COLLATE NOCASE
            LIMIT 5
        """, (query, query, query)).fetchall()
        return [dict(employee) for employee in matches]

    finally:
        connection.close()


def get_chat_employee_context(email: str, role: str, message: str):
    employees = get_chat_employee_records(email, role, message)
    if not employees:
        return ""

    message = message.lower()
    include_leave = any(
        term in message
        for term in ("leave", "vacation", "time off")
    )
    include_attendance = any(
        term in message
        for term in ("attendance", "clock", "timesheet", "absent")
    )

    connection = get_hr_db_connection()
    context_lines = [
        "Authorized employee records from the HR database:"
    ]

    try:
        for employee in employees:
            context_lines.extend([
                (
                    f"- {employee['first_name']} {employee['last_name']} "
                    f"(ID {employee['employee_code']}): "
                    f"{employee['job_title']}, {employee['department_name']}; "
                    f"hire date {employee['hire_date']}; "
                    f"status {'active' if employee['is_active'] else 'inactive'}."
                )
            ])

            leave_requests = []
            if include_leave:
                leave_requests = connection.execute("""
                    SELECT leave_type, start_date, end_date, status
                    FROM leave_requests
                    WHERE employee_id = ?
                    ORDER BY created_at DESC
                    LIMIT 5
                """, (employee["id"],)).fetchall()
            if leave_requests:
                context_lines.append("Recent leave requests:")
                context_lines.extend(
                    (
                        f"- {request['leave_type']} leave from "
                        f"{request['start_date']} to {request['end_date']}: "
                        f"{request['status']}."
                    )
                    for request in leave_requests
                )

            attendance = []
            if include_attendance:
                attendance = connection.execute("""
                    SELECT attendance_date, status, check_in, check_out
                    FROM attendance
                    WHERE employee_id = ?
                    ORDER BY attendance_date DESC
                    LIMIT 7
                """, (employee["id"],)).fetchall()
            if attendance:
                context_lines.append("Recent attendance:")
                context_lines.extend(
                    (
                        f"- {record['attendance_date']}: {record['status']}"
                        + (
                            f", {record['check_in']}–{record['check_out']}"
                            if record["check_in"] or record["check_out"]
                            else ""
                        )
                        + "."
                    )
                    for record in attendance
                )

        return "\n".join(context_lines)

    finally:
        connection.close()


def update_employee(employee_id: int, employee: dict):
    now = datetime.now(timezone.utc).isoformat()
    connection = get_hr_db_connection()

    try:
        cursor = connection.execute("""
            UPDATE employees
            SET
                employee_code = ?,
                first_name = ?,
                last_name = ?,
                email = ?,
                department_id = ?,
                job_title = ?,
                hire_date = ?,
                phone = ?,
                updated_at = ?
            WHERE id = ?
        """, (
            employee["employee_code"],
            employee["first_name"],
            employee["last_name"],
            employee["email"],
            employee["department_id"],
            employee["job_title"],
            employee["hire_date"],
            employee["phone"],
            now,
            employee_id
        ))
        connection.commit()
        return cursor.rowcount > 0

    finally:
        connection.close()


def deactivate_employee(employee_id: int):
    connection = get_hr_db_connection()

    try:
        cursor = connection.execute("""
            UPDATE employees
            SET is_active = 0, updated_at = ?
            WHERE id = ?
        """, (
            datetime.now(timezone.utc).isoformat(),
            employee_id
        ))
        connection.commit()
        return cursor.rowcount > 0

    finally:
        connection.close()


def get_dashboard_stats():
    connection = get_hr_db_connection()

    try:
        counts = connection.execute("""
            SELECT
                COUNT(*) AS total_employees,
                COALESCE(SUM(is_active), 0) AS active_employees,
                COALESCE(SUM(CASE WHEN is_active = 0 THEN 1 ELSE 0 END), 0)
                    AS inactive_employees
            FROM employees
        """).fetchone()
        department_count = connection.execute(
            "SELECT COUNT(*) FROM departments"
        ).fetchone()[0]

        return {
            **dict(counts),
            "department_count": department_count
        }

    finally:
        connection.close()
