# Authentication and roles

The `/register`, `/login`, and `/me` endpoints serve the chatbot. New registrations always receive the `employee` role; the public registration endpoint does not accept a role. Employees must verify their email and receive HR approval before login or access to existing tokens.

The registration form requires first and last name and accepts an optional phone number. Registration sends a time-limited, one-time verification link by email. HR sees the request only after the email is verified, then supplies the official employee ID, department, job title, and hire date when approving it. Email verification alone does not grant access: HR approval is also required. The authenticated `/me` endpoint returns the signed-in user's name, email, phone, and profile status from the verified registration or employee record. The chatbot displays those details and answers direct profile questions from the local database, saving the answer in that user's conversation without adding profile data to the external model prompt.

## Email verification configuration

Configure these values in the server's `.env` file. Use the public application URL so verification links point to the deployed service:

```env
APP_BASE_URL=https://chatbot.example.com
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=mailer@example.com
SMTP_PASSWORD=replace-with-a-mail-provider-password
SMTP_FROM_EMAIL=mailer@example.com
SMTP_TIMEOUT_SECONDS=15
```

`SMTP_SECURITY` accepts `starttls` (the default), `ssl`, or `none` for a trusted local relay. Username and password must either both be set or both be omitted. The link expires after 24 hours; resend requests are limited to one every 60 seconds per account. If mail delivery is not configured or fails during signup, the account and pending HR request remain stored, and the employee can use **Resend verification email** after delivery is configured.

Restart the API after changing `.env`. SMTP configuration errors are returned for missing or invalid settings; connection and authentication failures are logged server-side. A failed delivery clears that token's send cooldown so the employee can retry immediately.

Existing accounts are migrated as unverified. They must verify their email before access; existing employee registration approvals are preserved. An account with no registration approval must have its employee record established by HR. Bootstrap Super Admin and HR Admin accounts must verify their email but do not need an employee registration approval.

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

The login response and `/me` response include the user's role. `/me` also includes the profile details described above. The JWT carries a role claim, but authorization reads the current role and verification/HR status from SQLite so role changes, email verification requirements, and HR decisions take effect for already-issued tokens. Roles are `employee`, `hr_admin`, and `super_admin`.

An employee whose onboarding request is rejected cannot log in, and rejection immediately invalidates any tokens already issued to that account. Pending registrations cannot access the chatbot.

## Admin dashboard

Open `/admin` for the separate HR dashboard; `/` continues to serve the chatbot. HR Admins and Super Admins can create departments, add and edit employee records, search and filter the directory, and deactivate employees. Employee and department data is stored in `employees.db`; the chatbot's existing account and conversation data is unchanged.

From the project directory, start FastAPI with `.\venv\Scripts\python.exe -m uvicorn api:api --reload`, then open `http://localhost:8000/admin`. Configure the bootstrap Super Admin before signing in if you have not already done so.

Employees can open `/leave` or use **My leave requests** in the chatbot sidebar to submit annual, sick, or unpaid leave requests and see their own request history. HR Admins and Super Admins can review requests in `/admin`; employees cannot view other employees' requests, and reviewers cannot approve their own. Overlapping pending or approved leave dates are rejected. Leave balances and accrual rules are not calculated because no company policy has been configured.

Attendance is entered by HR in the dashboard and recorded once per employee per date; saving the same employee/date updates that record. The summary report aggregates leave requests, attendance statuses, and active headcount by department for a chosen date range.

The chatbot retrieves only the signed-in employee's own matching HR information. HR Admins and Super Admins can ask about a specific employee using their employee ID, email, or full name; it does not load the entire directory into a chat. Chat context excludes phone numbers and leave reasons.
