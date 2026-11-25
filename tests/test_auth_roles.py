import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["SUPER_ADMIN_EMAIL"] = ""
os.environ["SUPER_ADMIN_PASSWORD"] = ""

import auth
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials


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

    def test_registered_users_are_employees_and_receive_role_claim(self):
        user = auth.create_user("employee@example.test", "long-password")

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
        token = auth.create_access_token(
            user["id"],
            user["email"],
            user["role"]
        )

        self.assertTrue(
            self.hr_db.reject_employee_registration(
                registration_id,
                reviewer_id=1,
                rejection_note="Not eligible"
            )
        )
        self.assertIsNone(
            auth.authenticate_user("employee@example.test", "long-password")
        )
        with self.assertRaises(HTTPException) as error:
            auth.get_current_user(
                HTTPAuthorizationCredentials(
                    scheme="Bearer",
                    credentials=token
                )
            )

        self.assertEqual(error.exception.status_code, 401)

    def test_role_dependency_rejects_employees(self):
        require_hr_admin = auth.require_roles("hr_admin")

        with self.assertRaises(HTTPException) as error:
            require_hr_admin({"id": 1, "role": "employee"})

        self.assertEqual(error.exception.status_code, 403)

    def test_super_admin_bootstrap_is_idempotent_and_does_not_reset_password(self):
        with patch.object(auth, "SUPER_ADMIN_EMAIL", "admin@example.test"), \
                patch.object(auth, "SUPER_ADMIN_PASSWORD", "a-strong-password"):
            auth.initialize_database()

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

        with patch.object(auth, "SUPER_ADMIN_EMAIL", "admin@example.com"), \
                patch.object(auth, "SUPER_ADMIN_PASSWORD", "a-strong-password"):
            auth.initialize_database()

    def test_api_role_assignment_is_super_admin_only_and_database_backed(self):
        registration = self.client.post(
            "/register",
            json={
                "email": "employee@example.com",
                "password": "employee-password",
                "role": "super_admin"
            }
        )
        self.assertEqual(registration.status_code, 201)
        self.assertEqual(registration.json()["user"]["role"], "employee")

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
        self.assertEqual(registration.json()["user"]["role"], "employee")
        employee_token = self.client.post(
            "/login",
            json={
                "email": "new.person@example.com",
                "password": "employee-password"
            }
        ).json()["access_token"]
        employee_headers = {
            "Authorization": f"Bearer {employee_token}"
        }
        pending_profile = self.client.get(
            "/me",
            headers=employee_headers
        ).json()["profile"]
        self.assertEqual(pending_profile["first_name"], "New")
        self.assertEqual(pending_profile["email"], "new.person@example.com")
        self.assertEqual(pending_profile["phone"], "+1-555-0100")
        self.assertEqual(pending_profile["status"], "pending")
        self.assertEqual(
            self.client.get(
                "/admin/employee-registrations",
                headers=employee_headers
            ).status_code,
            403
        )

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
        registration = self.client.post(
            "/register",
            json={
                "email": "employee@example.com",
                "password": "employee-password"
            }
        )
        self.assertEqual(registration.status_code, 201)
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

        self.client.post(
            "/register",
            json={
                "email": "person@example.com",
                "password": "employee-password"
            }
        )
        self.client.post(
            "/register",
            json={
                "email": "other@example.com",
                "password": "employee-password"
            }
        )
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
        self.client.post(
            "/register",
            json={
                "email": "employee@example.com",
                "password": "employee-password"
            }
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
        self.client.post(
            "/register",
            json={
                "email": "profile@example.com",
                "password": "profile-password",
                "first_name": "Profile",
                "last_name": "Employee",
                "phone": "+1-555-0199"
            }
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
