import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["SUPER_ADMIN_EMAIL"] = ""
os.environ["SUPER_ADMIN_PASSWORD"] = ""

import auth
import email_verification
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials


class EmailVerificationDeliveryTests(unittest.TestCase):
    def test_verification_email_uses_configured_starttls_smtp(self):
        settings = {
            "APP_BASE_URL": "https://support.example.test",
            "SMTP_HOST": "smtp.example.test",
            "SMTP_PORT": "587",
            "SMTP_SECURITY": "starttls",
            "SMTP_USERNAME": "mailer@example.test",
            "SMTP_PASSWORD": "mail-password",
            "SMTP_FROM_EMAIL": "mailer@example.test",
            "SMTP_TIMEOUT_SECONDS": "10"
        }
        with patch.dict(os.environ, settings), patch.object(
            email_verification.smtplib,
            "SMTP"
        ) as smtp_class:
            smtp = smtp_class.return_value.__enter__.return_value
            email_verification.send_verification_email(
                "employee@example.test",
                "one-time-token"
            )

        smtp_class.assert_called_once_with(
            "smtp.example.test",
            587,
            timeout=10.0
        )
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with(
            "mailer@example.test",
            "mail-password"
        )
        message = smtp.send_message.call_args.args[0]
        self.assertEqual(message["To"], "employee@example.test")
        self.assertIn(
            "https://support.example.test/verify-email?token=one-time-token",
            message.get_content()
        )


class AuthRoleTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database_path = Path(self.temp_dir.name) / "users.db"
        self.hr_database_path = Path(self.temp_dir.name) / "employees.db"
        self.db_path_patch = patch.object(auth, "DB_PATH", self.database_path)
        import hr_db
        self.hr_db = hr_db
        self.hr_db_path_patch = patch.object(
            hr_db,
            "DB_PATH",
            self.hr_database_path
        )
        self.email_patch = patch.object(auth, "SUPER_ADMIN_EMAIL", "")
        self.password_patch = patch.object(auth, "SUPER_ADMIN_PASSWORD", "")
        self.db_path_patch.start()
        self.hr_db_path_patch.start()
        self.email_patch.start()
        self.password_patch.start()
        self.addCleanup(self.db_path_patch.stop)
        self.addCleanup(self.hr_db_path_patch.stop)
        self.addCleanup(self.email_patch.stop)
        self.addCleanup(self.password_patch.stop)
        auth.initialize_database()
        self.hr_db.initialize_hr_database()

    def verify_email(self, user_id):
        token = auth.create_email_verification_token(user_id)
        self.assertIsNotNone(token)
        self.assertTrue(auth.verify_email_token(token))
        return token

    def approve_registration(self, registration_id):
        department_id = self.hr_db.create_department("Test Department")
        return self.hr_db.approve_employee_registration(
            registration_id=registration_id,
            first_name="Test",
            last_name="Employee",
            employee_code="TEST-001",
            department_id=department_id,
            job_title="Tester",
            hire_date="2026-01-01",
            reviewer_id=1
        )

    def test_registered_users_are_employees_and_receive_role_claim(self):
        user = auth.create_user("employee@example.test", "long-password")
        registration_id = self.hr_db.create_employee_registration(
            user_id=user["id"],
            email=user["email"],
            first_name="Test",
            last_name="Employee",
            phone=None
        )

        with self.assertRaises(HTTPException) as unverified_error:
            auth.authenticate_user("employee@example.test", "long-password")
        self.assertEqual(unverified_error.exception.status_code, 403)

        self.verify_email(user["id"])
        with self.assertRaises(HTTPException) as pending_error:
            auth.authenticate_user("employee@example.test", "long-password")
        self.assertEqual(pending_error.exception.status_code, 403)
        pending_token = auth.create_access_token(
            user["id"],
            user["email"],
            user["role"]
        )
        with self.assertRaises(HTTPException) as pending_token_error:
            auth.get_current_user(
                HTTPAuthorizationCredentials(
                    scheme="Bearer",
                    credentials=pending_token
                )
            )
        self.assertEqual(pending_token_error.exception.status_code, 403)

        self.approve_registration(registration_id)

        self.assertEqual(user["role"], "employee")
        authenticated_user = auth.authenticate_user(
            "employee@example.test",
            "long-password"
        )
        self.assertEqual(authenticated_user["role"], "employee")

        token = auth.create_access_token(
            authenticated_user["id"],
            authenticated_user["email"],
            authenticated_user["role"]
        )
        payload = auth.jwt.decode(
            token,
            auth.JWT_SECRET_KEY,
            algorithms=[auth.JWT_ALGORITHM]
        )
        self.assertEqual(payload["role"], "employee")

    def test_current_user_uses_latest_database_role(self):
        user = auth.create_user("employee@example.test", "long-password")
        self.verify_email(user["id"])
        token = auth.create_access_token(
            user["id"],
            user["email"],
            user["role"]
        )

        self.assertTrue(
            auth.set_user_role(user["email"], "hr_admin")
        )
        current_user = auth.get_current_user(
            HTTPAuthorizationCredentials(
                scheme="Bearer",
                credentials=token
            )
        )

        self.assertEqual(current_user["role"], "hr_admin")

    def test_rejected_registration_blocks_login_and_existing_tokens(self):
        user = auth.create_user("employee@example.test", "long-password")
        registration_id = self.hr_db.create_employee_registration(
            user_id=user["id"],
            email=user["email"],
            first_name="Test",
            last_name="Employee",
            phone=None
        )
        self.verify_email(user["id"])
        self.approve_registration(registration_id)
        token = auth.create_access_token(
            user["id"],
            user["email"],
            user["role"]
        )

        connection = self.hr_db.get_hr_db_connection()
        try:
            connection.execute(
                """
                UPDATE employee_registrations
                SET status = 'rejected'
                WHERE id = ?
                """,
                (registration_id,)
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(HTTPException) as login_error:
            auth.authenticate_user("employee@example.test", "long-password")
        self.assertEqual(login_error.exception.status_code, 403)
        with self.assertRaises(HTTPException) as error:
            auth.get_current_user(
                HTTPAuthorizationCredentials(
                    scheme="Bearer",
                    credentials=token
                )
            )

        self.assertEqual(error.exception.status_code, 403)

    def test_verification_tokens_are_expiring_and_single_use(self):
        user = auth.create_user("employee@example.test", "long-password")
        token = self.verify_email(user["id"])
        self.assertFalse(auth.verify_email_token(token))

        second_user = auth.create_user("expired@example.test", "long-password")
        with patch.object(auth, "EMAIL_VERIFICATION_EXPIRE_HOURS", -1):
            expired_token = auth.create_email_verification_token(
                second_user["id"]
            )
        self.assertFalse(auth.verify_email_token(expired_token))

        third_user = auth.create_user("retry@example.test", "long-password")
        failed_delivery_token = auth.create_email_verification_token(
            third_user["id"]
        )
        auth.discard_email_verification_token(
            third_user["id"],
            failed_delivery_token
        )
        self.assertIsNotNone(
            auth.create_email_verification_token(third_user["id"])
        )

    def test_existing_users_migrate_as_unverified(self):
        connection = auth.get_db_connection()
        try:
            connection.execute("DROP TABLE users")
            connection.execute("""
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            connection.execute(
                """
                INSERT INTO users (email, password_hash, created_at)
                VALUES (?, ?, ?)
                """,
                (
                    "legacy@example.test",
                    "legacy-password-hash",
                    "2026-01-01T00:00:00+00:00"
                )
            )
            connection.commit()
        finally:
            connection.close()

        auth.initialize_database()
        legacy_user = auth.get_user_by_email("legacy@example.test")

        self.assertFalse(legacy_user["email_verified"])

    def test_role_dependency_rejects_employees(self):
        require_hr_admin = auth.require_roles("hr_admin")

        with self.assertRaises(HTTPException) as error:
            require_hr_admin({"id": 1, "role": "employee"})

        self.assertEqual(error.exception.status_code, 403)

    def test_super_admin_bootstrap_is_idempotent_and_does_not_reset_password(self):
        with patch.object(auth, "SUPER_ADMIN_EMAIL", "admin@example.test"), \
                patch.object(auth, "SUPER_ADMIN_PASSWORD", "a-strong-password"):
            auth.initialize_database()

        super_admin_user = auth.get_user_by_email("admin@example.test")
        self.assertFalse(super_admin_user["email_verified"])
        with self.assertRaises(HTTPException):
            auth.authenticate_user(
                "admin@example.test",
                "a-strong-password"
            )
        self.verify_email(super_admin_user["id"])

        with patch.object(auth, "SUPER_ADMIN_EMAIL", "admin@example.test"), \
                patch.object(auth, "SUPER_ADMIN_PASSWORD", "a-different-password"):
            auth.initialize_database()

        super_admin = auth.authenticate_user(
            "admin@example.test",
            "a-strong-password"
        )
        self.assertEqual(super_admin["role"], "super_admin")
        self.assertIsNone(
            auth.authenticate_user(
                "admin@example.test",
                "a-different-password"
            )
        )

    def test_bootstrap_refuses_to_promote_an_existing_employee(self):
        auth.create_user("employee@example.test", "long-password")

        with patch.object(auth, "SUPER_ADMIN_EMAIL", "employee@example.test"), \
                patch.object(auth, "SUPER_ADMIN_PASSWORD", "a-strong-password"):
            with self.assertRaises(RuntimeError):
                auth.initialize_database()


class ApiAuthRoleTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        import hr_db

        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.hr_db = hr_db
        self.verification_tokens = {}
        self.patches = [
            patch.object(
                auth,
                "DB_PATH",
                Path(self.temp_dir.name) / "users.db"
            ),
            patch.object(auth, "SUPER_ADMIN_EMAIL", ""),
            patch.object(auth, "SUPER_ADMIN_PASSWORD", ""),
            patch.object(
                hr_db,
                "DB_PATH",
                Path(self.temp_dir.name) / "employees.db"
            )
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

        auth.initialize_database()
        hr_db.initialize_hr_database()

        import api

        self.api = api
        self.client = TestClient(api.api)
        self.mail_patch = patch.object(
            api,
            "send_verification_email",
            side_effect=lambda email, token: self.verification_tokens.update(
                {email.lower(): token}
            )
        )
        self.mail_patch.start()
        self.addCleanup(self.mail_patch.stop)

        with patch.object(auth, "SUPER_ADMIN_EMAIL", "admin@example.com"), \
                patch.object(auth, "SUPER_ADMIN_PASSWORD", "a-strong-password"):
            auth.initialize_database()
        admin = auth.get_user_by_email("admin@example.com")
        admin_token = auth.create_email_verification_token(admin["id"])
        self.assertTrue(auth.verify_email_token(admin_token))

    def verify_registration_email(self, email):
        response = self.client.post(
            "/verify-email",
            json={"token": self.verification_tokens[email.lower()]}
        )
        self.assertEqual(response.status_code, 200)

    def verify_existing_account(self, email):
        user = auth.get_user_by_email(email)
        token = auth.create_email_verification_token(user["id"])
        self.assertIsNotNone(token)
        self.assertTrue(auth.verify_email_token(token))

    def approve_registration(self, email):
        registration = next(
            item
            for item in self.hr_db.list_employee_registrations("all")
            if item["email"].lower() == email.lower()
        )
        department_id = self.hr_db.create_department(
            f"Test Department {registration['id']}"
        )
        return self.hr_db.approve_employee_registration(
            registration_id=registration["id"],
            first_name=registration["first_name"],
            last_name=registration["last_name"],
            employee_code=f"TEST-{registration['id']:04d}",
            department_id=department_id,
            job_title="Tester",
            hire_date="2026-01-01",
            reviewer_id=auth.get_user_by_email("admin@example.com")["id"]
        )

    def register_and_verify_employee(
        self,
        email,
        password,
        first_name="Test",
        last_name="Employee",
        phone=None,
        approve=True
    ):
        response = self.client.post(
            "/register",
            json={
                "email": email,
                "password": password,
                "first_name": first_name,
                "last_name": last_name,
                "phone": phone
            }
        )
        self.assertEqual(response.status_code, 201)
        self.verify_registration_email(email)
        if approve:
            self.approve_registration(email)
        return response

    def create_directory_employee(self, email, first_name, last_name, code):
        department_id = self.hr_db.create_department(f"Department {code}")
        return self.hr_db.create_employee({
            "employee_code": code,
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "department_id": department_id,
            "job_title": "Tester",
            "hire_date": "2026-01-01",
            "phone": None
        })

    def test_api_role_assignment_is_super_admin_only_and_database_backed(self):
        registration = self.client.post(
            "/register",
            json={
                "email": "employee@example.com",
                "password": "employee-password",
                "first_name": "Test",
                "last_name": "Employee",
                "role": "super_admin"
            }
        )
        self.assertEqual(registration.status_code, 201)
        self.assertEqual(registration.json()["user"]["role"], "employee")
        self.verify_registration_email("employee@example.com")
        self.approve_registration("employee@example.com")

        employee_login = self.client.post(
            "/login",
            json={
                "email": "employee@example.com",
                "password": "employee-password"
            }
        ).json()
        employee_headers = {
            "Authorization": f"Bearer {employee_login['access_token']}"
        }

        forbidden = self.client.put(
            "/admin/users/role",
            headers=employee_headers,
            json={"email": "employee@example.com", "role": "hr_admin"}
        )
        self.assertEqual(forbidden.status_code, 403)

        admin_login = self.client.post(
            "/login",
            json={
                "email": "admin@example.com",
                "password": "a-strong-password"
            }
        ).json()
        admin_headers = {
            "Authorization": f"Bearer {admin_login['access_token']}"
        }
        updated = self.client.put(
            "/admin/users/role",
            headers=admin_headers,
            json={"email": "employee@example.com", "role": "hr_admin"}
        )
        self.assertEqual(updated.status_code, 200)

        current_user = self.client.get("/me", headers=employee_headers)
        self.assertEqual(current_user.json()["user"]["role"], "hr_admin")

        hr_login = self.client.post(
            "/login",
            json={
                "email": "employee@example.com",
                "password": "employee-password"
            }
        ).json()
        self.assertEqual(hr_login["user"]["role"], "hr_admin")
        self.assertEqual(
            self.client.get(
                "/admin/dashboard/stats",
                headers={
                    "Authorization": f"Bearer {hr_login['access_token']}"
                }
            ).status_code,
            200
        )

    def test_registration_details_wait_for_hr_verification_before_directory_entry(self):
        registration = self.client.post(
            "/register",
            json={
                "email": "new.person@example.com",
                "password": "employee-password",
                "first_name": "New",
                "last_name": "Person",
                "phone": "+1-555-0100",
                "role": "super_admin"
            }
        )
        self.assertEqual(registration.status_code, 201)
        self.assertEqual(
            registration.json()["employee_registration_status"],
            "pending"
        )
        self.assertTrue(registration.json()["email_verification_required"])
        self.assertEqual(registration.json()["user"]["role"], "employee")
        unverified_login = self.client.post(
            "/login",
            json={
                "email": "new.person@example.com",
                "password": "employee-password"
            }
        )
        self.assertEqual(unverified_login.status_code, 403)

        admin_token = self.client.post(
            "/login",
            json={
                "email": "admin@example.com",
                "password": "a-strong-password"
            }
        ).json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        pending = self.client.get(
            "/admin/employee-registrations",
            headers=admin_headers
        ).json()["registrations"]
        self.assertEqual(pending, [])

        self.verify_registration_email("new.person@example.com")
        awaiting_hr_login = self.client.post(
            "/login",
            json={
                "email": "new.person@example.com",
                "password": "employee-password"
            }
        )
        self.assertEqual(awaiting_hr_login.status_code, 403)
        pending = self.client.get(
            "/admin/employee-registrations",
            headers=admin_headers
        ).json()["registrations"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["email"], "new.person@example.com")
        self.assertEqual(
            self.client.get(
                "/admin/employees?search=new.person@example.com",
                headers=admin_headers
            ).json()["employees"],
            []
        )

        department_id = self.client.post(
            "/admin/departments",
            headers=admin_headers,
            json={"name": "Customer Success"}
        ).json()["department"]["id"]
        approval = self.client.post(
            f"/admin/employee-registrations/{pending[0]['id']}/approve",
            headers=admin_headers,
            json={
                "first_name": "New",
                "last_name": "Person",
                "employee_code": "EMP-NEW-1",
                "department_id": department_id,
                "job_title": "Support Specialist",
                "hire_date": "2026-01-05"
            }
        )

        self.assertEqual(approval.status_code, 200)
        self.assertEqual(approval.json()["registration"]["status"], "approved")
        employee = approval.json()["employee"]
        self.assertEqual(employee["first_name"], "New")
        self.assertEqual(employee["phone"], "+1-555-0100")
        employee_login = self.client.post(
            "/login",
            json={
                "email": "new.person@example.com",
                "password": "employee-password"
            }
        )
        self.assertEqual(employee_login.status_code, 200)
        employee_headers = {
            "Authorization": f"Bearer {employee_login.json()['access_token']}"
        }
        verified_profile = self.client.get(
            "/me",
            headers=employee_headers
        ).json()["profile"]
        self.assertEqual(verified_profile["status"], "verified")
        self.assertEqual(verified_profile["first_name"], "New")
        self.assertEqual(verified_profile["phone"], "+1-555-0100")
        self.assertEqual(
            self.client.get(
                "/admin/employees?search=new.person@example.com",
                headers=admin_headers
            ).json()["employees"][0]["employee_code"],
            "EMP-NEW-1"
        )

    def test_employee_directory_crud_search_and_dashboard_stats(self):
        auth.create_user("employee@example.com", "employee-password")
        self.verify_existing_account("employee@example.com")

        admin_token = self.client.post(
            "/login",
            json={
                "email": "admin@example.com",
                "password": "a-strong-password"
            }
        ).json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        self.assertEqual(self.client.get("/admin").status_code, 200)
        self.assertEqual(self.client.get("/leave").status_code, 200)
        department_response = self.client.post(
            "/admin/departments",
            headers=admin_headers,
            json={"name": "Engineering"}
        )
        self.assertEqual(department_response.status_code, 201)
        department_id = department_response.json()["department"]["id"]

        employee_payload = {
            "employee_code": "ENG-001",
            "first_name": "Avery",
            "last_name": "Lee",
            "email": "employee@example.com",
            "department_id": department_id,
            "job_title": "Engineer",
            "hire_date": "2025-01-15",
            "phone": None
        }
        created = self.client.post(
            "/admin/employees",
            headers=admin_headers,
            json=employee_payload
        )
        self.assertEqual(created.status_code, 201)
        employee_id = created.json()["employee"]["id"]

        employee_token = self.client.post(
            "/login",
            json={
                "email": "employee@example.com",
                "password": "employee-password"
            }
        ).json()["access_token"]
        employee_headers = {"Authorization": f"Bearer {employee_token}"}
        self.assertEqual(
            self.client.get(
                "/admin/dashboard/stats",
                headers=employee_headers
            ).status_code,
            403
        )

        duplicate = self.client.post(
            "/admin/employees",
            headers=admin_headers,
            json=employee_payload
        )
        self.assertEqual(duplicate.status_code, 409)

        search = self.client.get(
            "/admin/employees?search=avery",
            headers=admin_headers
        )
        self.assertEqual(len(search.json()["employees"]), 1)

        employee_payload["job_title"] = "Senior Engineer"
        updated = self.client.put(
            f"/admin/employees/{employee_id}",
            headers=admin_headers,
            json=employee_payload
        )
        self.assertEqual(
            updated.json()["employee"]["job_title"],
            "Senior Engineer"
        )

        deactivated = self.client.patch(
            f"/admin/employees/{employee_id}/deactivate",
            headers=admin_headers
        )
        self.assertEqual(deactivated.json()["employee"]["is_active"], 0)
        stats = self.client.get(
            "/admin/dashboard/stats",
            headers=admin_headers
        ).json()
        self.assertEqual(stats["total_employees"], 1)
        self.assertEqual(stats["active_employees"], 0)
        self.assertEqual(stats["inactive_employees"], 1)

    def test_leave_attendance_reporting_and_chatbot_access_boundaries(self):
        admin_token = self.client.post(
            "/login",
            json={
                "email": "admin@example.com",
                "password": "a-strong-password"
            }
        ).json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        auth.create_user("person@example.com", "employee-password")
        auth.create_user("other@example.com", "employee-password")
        self.verify_existing_account("person@example.com")
        self.verify_existing_account("other@example.com")
        department_id = self.client.post(
            "/admin/departments",
            headers=admin_headers,
            json={"name": "Operations"}
        ).json()["department"]["id"]

        person_record = {
            "employee_code": "OPS-001",
            "first_name": "Taylor",
            "last_name": "Rivera",
            "email": "person@example.com",
            "department_id": department_id,
            "job_title": "Coordinator",
            "hire_date": "2024-06-01",
            "phone": None
        }
        person_id = self.client.post(
            "/admin/employees",
            headers=admin_headers,
            json=person_record
        ).json()["employee"]["id"]
        other_record = {
            **person_record,
            "employee_code": "OPS-002",
            "first_name": "Morgan",
            "email": "other@example.com"
        }
        self.client.post(
            "/admin/employees",
            headers=admin_headers,
            json=other_record
        )

        employee_view_of_other = self.api.get_chat_employee_context(
            "person@example.com",
            "employee",
            "What department does Morgan Rivera work in?"
        )
        self.assertEqual(employee_view_of_other, "")
        hr_view_of_other = self.api.get_chat_employee_context(
            "admin@example.com",
            "super_admin",
            "What department is OPS-002 in?"
        )
        self.assertIn("Morgan Rivera", hr_view_of_other)
        self.assertNotIn("Taylor Rivera", hr_view_of_other)

        person_token = self.client.post(
            "/login",
            json={
                "email": "person@example.com",
                "password": "employee-password"
            }
        ).json()["access_token"]
        other_token = self.client.post(
            "/login",
            json={
                "email": "other@example.com",
                "password": "employee-password"
            }
        ).json()["access_token"]
        person_headers = {"Authorization": f"Bearer {person_token}"}
        other_headers = {"Authorization": f"Bearer {other_token}"}

        leave_payload = {
            "leave_type": "annual",
            "start_date": "2026-12-01",
            "end_date": "2026-12-03",
            "reason": "Personal time"
        }
        leave_response = self.client.post(
            "/leave-requests",
            headers=person_headers,
            json=leave_payload
        )
        self.assertEqual(leave_response.status_code, 201)
        leave_id = leave_response.json()["leave_request"]["id"]
        self.assertEqual(
            len(self.client.get(
                "/leave-requests",
                headers=person_headers
            ).json()["leave_requests"]),
            1
        )
        self.assertEqual(
            len(self.client.get(
                "/leave-requests",
                headers=other_headers
            ).json()["leave_requests"]),
            0
        )
        self.assertEqual(
            self.client.get(
                "/admin/attendance",
                headers=person_headers
            ).status_code,
            403
        )
        overlapping = self.client.post(
            "/leave-requests",
            headers=person_headers,
            json=leave_payload
        )
        self.assertEqual(overlapping.status_code, 409)

        decision = self.client.patch(
            f"/admin/leave-requests/{leave_id}/decision",
            headers=admin_headers,
            json={"status": "approved", "review_note": "Approved"}
        )
        self.assertEqual(decision.json()["leave_request"]["status"], "approved")

        attendance_payload = {
            "employee_id": person_id,
            "attendance_date": "2026-11-20",
            "status": "present",
            "check_in": "09:00",
            "check_out": "17:00",
            "note": None
        }
        attendance_response = self.client.put(
            "/admin/attendance",
            headers=admin_headers,
            json=attendance_payload
        )
        self.assertEqual(attendance_response.status_code, 200)
        attendance_payload["status"] = "remote"
        updated_attendance = self.client.put(
            "/admin/attendance",
            headers=admin_headers,
            json=attendance_payload
        )
        self.assertEqual(
            updated_attendance.json()["attendance"]["status"],
            "remote"
        )

        report = self.client.get(
            "/admin/reports/summary?start_date=2026-11-01&end_date=2026-12-31",
            headers=admin_headers
        ).json()
        self.assertEqual(report["leave_by_status"]["approved"], 1)
        self.assertEqual(report["attendance_by_status"]["remote"], 1)

        with patch.object(
            self.api.graph_app,
            "invoke",
            return_value={"response": "Your department is Operations.", "category": "General"}
        ) as graph_invoke, patch.object(
            self.api,
            "get_user_conversation",
            return_value=None
        ), patch.object(self.api, "create_conversation"), \
                patch.object(self.api, "save_message"):
            chat_response = self.client.post(
                "/chat",
                headers=person_headers,
                json={"message": "What department am I in?"}
            )

        self.assertEqual(chat_response.status_code, 200)
        graph_state = graph_invoke.call_args.args[0]
        self.assertIn("OPS-001", graph_state["employee_context"])
        self.assertNotIn("Morgan", graph_state["employee_context"])

    def test_existing_chat_route_still_works_with_role_aware_user(self):
        auth.create_user("employee@example.com", "employee-password")
        self.verify_existing_account("employee@example.com")
        self.create_directory_employee(
            "employee@example.com",
            "Test",
            "Employee",
            "CHAT-001"
        )
        login = self.client.post(
            "/login",
            json={
                "email": "employee@example.com",
                "password": "employee-password"
            }
        ).json()

        with patch.object(
            self.api.graph_app,
            "invoke",
            return_value={"response": "Test reply", "category": "General"}
        ), patch.object(self.api, "get_user_conversation", return_value=None), \
                patch.object(self.api, "create_conversation"), \
                patch.object(self.api, "save_message"):
            response = self.client.post(
                "/chat",
                headers={"Authorization": f"Bearer {login['access_token']}"},
                json={"message": "Hello"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["response"], "Test reply")

    def test_profile_questions_are_answered_from_the_authenticated_profile(self):
        self.register_and_verify_employee(
            "profile@example.com",
            "profile-password",
            first_name="Profile",
            last_name="Employee",
            phone="+1-555-0199"
        )
        login = self.client.post(
            "/login",
            json={
                "email": "profile@example.com",
                "password": "profile-password"
            }
        ).json()
        headers = {"Authorization": f"Bearer {login['access_token']}"}

        with patch.object(
            self.api.graph_app,
            "invoke"
        ) as graph_invoke, patch.object(
            self.api,
            "get_user_conversation",
            return_value=None
        ), patch.object(self.api, "create_conversation"), patch.object(
            self.api,
            "save_message"
        ) as save_message:
            response = self.client.post(
                "/chat",
                headers=headers,
                json={"message": "What is my phone number?"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("+1-555-0199", response.json()["response"])
        self.assertEqual(response.json()["category"], "Account")
        graph_invoke.assert_not_called()
        self.assertEqual(
            save_message.call_args_list[-1].kwargs["content"],
            response.json()["response"]
        )


if __name__ == "__main__":
    unittest.main()
