# Authentication and roles

The existing `/register`, `/login`, and `/me` endpoints continue to serve the chatbot. New registrations always receive the `employee` role; the public registration endpoint does not accept a role.

The chatbot's registration form now asks for first and last name plus an optional phone number. Those details appear as a pending request in the HR dashboard, not as a verified directory entry. HR verifies the name and supplies the official employee ID, department, job title, and hire date when approving the request. The authenticated `/me` endpoint returns the signed-in user's name, email, phone, and profile status from the pending request or verified employee record. The chatbot displays those details and answers direct profile questions from the local database, saving the answer in that user's conversation without adding profile data to the external model prompt. Older API clients that send only email and password remain supported, but do not submit an onboarding request.

## Bootstrap the first Super Admin

Add both settings to the server's `.env` file:

```env
SUPER_ADMIN_EMAIL=admin@example.com
SUPER_ADMIN_PASSWORD=replace-with-a-unique-password-of-at-least-12-characters
```

On startup, the app creates this account only if the email is unused. If an account with that email already exists but is not a Super Admin, startup stops rather than silently promoting it. If the account is already a Super Admin, startup leaves its password unchanged. Keep both settings unset to disable bootstrap behavior.

Existing accounts are migrated as `employee`. After logging in as Super Admin, assign an employee or HR Admin role with:

```http
PUT /admin/users/role
Authorization: Bearer <super-admin-access-token>
Content-Type: application/json

{"email":"person@example.com","role":"hr_admin"}
```

The endpoint accepts only `employee` and `hr_admin`; it cannot create or demote Super Admins, and a Super Admin cannot change their own role. Requests from employees and HR Admins receive `403 Forbidden`.

The login response and `/me` response include the user's role. `/me` also includes the profile details described above. The JWT carries a role claim, but authorization reads the current role from SQLite so role changes take effect for already-issued tokens. Roles are `employee`, `hr_admin`, and `super_admin`.

## Admin dashboard

Open `/admin` for the separate HR dashboard; `/` continues to serve the chatbot. HR Admins and Super Admins can create departments, add and edit employee records, search and filter the directory, and deactivate employees. Employee and department data is stored in `employees.db`; the chatbot's existing account and conversation data is unchanged.

From the project directory, start FastAPI with `.\venv\Scripts\python.exe -m uvicorn api:api --reload`, then open `http://localhost:8000/admin`. Configure the bootstrap Super Admin before signing in if you have not already done so.

Employees can open `/leave` or use **My leave requests** in the chatbot sidebar to submit annual, sick, or unpaid leave requests and see their own request history. HR Admins and Super Admins can review requests in `/admin`; employees cannot view other employees' requests, and reviewers cannot approve their own. Overlapping pending or approved leave dates are rejected. Leave balances and accrual rules are not calculated because no company policy has been configured.

Attendance is entered by HR in the dashboard and recorded once per employee per date; saving the same employee/date updates that record. The summary report aggregates leave requests, attendance statuses, and active headcount by department for a chosen date range.

The chatbot retrieves only the signed-in employee's own matching HR information. HR Admins and Super Admins can ask about a specific employee using their employee ID, email, or full name; it does not load the entire directory into a chat. Chat context excludes phone numbers and leave reasons.
