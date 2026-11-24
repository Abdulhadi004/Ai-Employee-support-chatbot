
import os
import sqlite3
import jwt

from pathlib import Path
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from pwdlib import PasswordHash

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials


# Load environment variables
BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")

if not JWT_SECRET_KEY:
    raise ValueError("JWT_SECRET_KEY not found in .env file")

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
SUPER_ADMIN_EMAIL = os.getenv("SUPER_ADMIN_EMAIL", "").strip().lower()
SUPER_ADMIN_PASSWORD = os.getenv("SUPER_ADMIN_PASSWORD", "")
USER_ROLES = frozenset({"employee", "hr_admin", "super_admin"})
ASSIGNABLE_ROLES = frozenset({"employee", "hr_admin"})

# Password hashing
password_hash = PasswordHash.recommended()

# Bearer token authentication
security = HTTPBearer(auto_error=False)

# SQLite database
DB_PATH = BASE_DIR / "users.db"


# ---------------------------------
# DATABASE INITIALIZATION
# ---------------------------------

def get_db_connection():

    connection = sqlite3.connect(DB_PATH)

    connection.row_factory = sqlite3.Row

    return connection



def initialize_database():

    connection = get_db_connection()

    try:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'employee',
                created_at TEXT NOT NULL
            )
        """)

        # Check whether the role column already exists
        columns = connection.execute(
            "PRAGMA table_info(users)"
        ).fetchall()

        column_names = [column["name"] for column in columns]

        # Safely upgrade existing databases
        if "role" not in column_names:
            connection.execute("""
                ALTER TABLE users
                ADD COLUMN role TEXT NOT NULL DEFAULT 'employee'
            """)

        placeholders = ", ".join("?" for _ in USER_ROLES)
        connection.execute(
            f"UPDATE users SET role = 'employee' WHERE role NOT IN ({placeholders})",
            tuple(USER_ROLES)
        )

        if bool(SUPER_ADMIN_EMAIL) != bool(SUPER_ADMIN_PASSWORD):
            raise ValueError(
                "Set both SUPER_ADMIN_EMAIL and SUPER_ADMIN_PASSWORD, or leave both unset."
            )

        if SUPER_ADMIN_EMAIL:
            if len(SUPER_ADMIN_PASSWORD) < 12:
                raise ValueError(
                    "SUPER_ADMIN_PASSWORD must be at least 12 characters long."
                )

            super_admin = connection.execute(
                "SELECT role FROM users WHERE email = ?",
                (SUPER_ADMIN_EMAIL,)
            ).fetchone()

            if super_admin is None:
                connection.execute(
                    """
                    INSERT INTO users (email, password_hash, role, created_at)
                    VALUES (?, ?, 'super_admin', ?)
                    """,
                    (
                        SUPER_ADMIN_EMAIL,
                        password_hash.hash(SUPER_ADMIN_PASSWORD),
                        datetime.now(timezone.utc).isoformat()
                    )
                )
            elif super_admin["role"] != "super_admin":
                raise RuntimeError(
                    "SUPER_ADMIN_EMAIL already belongs to a non-super-admin account. "
                    "Use a new email or promote the account through a trusted database operation."
                )

        connection.commit()

        print("User database initialized successfully!")

    finally:
        connection.close()



# ---------------------------------
# USER REGISTRATION
# ---------------------------------

def create_user(email: str, password: str):

    email = email.strip().lower()

    hashed_password = password_hash.hash(password)

    connection = get_db_connection()

    try:

        cursor = connection.execute(
            """
            INSERT INTO users (email, password_hash, created_at)
            VALUES (?, ?, ?)
            """,
            (
                email,
                hashed_password,
                datetime.now(timezone.utc).isoformat()
            )
        )

        connection.commit()

        return {
            "id": cursor.lastrowid,
            "email": email,
            "role": "employee"
        }

    except sqlite3.IntegrityError:

        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists."
        )

    finally:
        connection.close()


def delete_user_account(user_id: int):
    connection = get_db_connection()

    try:
        cursor = connection.execute(
            "DELETE FROM users WHERE id = ?",
            (user_id,)
        )
        connection.commit()
        return cursor.rowcount > 0

    finally:
        connection.close()


# ---------------------------------
# USER LOGIN
# ---------------------------------

def authenticate_user(email: str, password: str):

    email = email.strip().lower()

    connection = get_db_connection()

    try:

        user = connection.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,)
        ).fetchone()

    finally:
        connection.close()

    if not user:
        return None

    if not password_hash.verify(
        password,
        user["password_hash"]
    ):
        return None

    return {
        "id": user["id"],
        "email": user["email"],
        "role": user["role"]
    }


# ---------------------------------
# CREATE JWT ACCESS TOKEN
# ---------------------------------

def create_access_token(
    user_id: int,
    email: str,
    role: str = "employee"
):

    if role not in USER_ROLES:
        raise ValueError("Invalid user role.")

    expiration = datetime.now(timezone.utc) + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )

    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "exp": expiration
    }

    token = jwt.encode(
        payload,
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM
    )

    return token


def get_user_by_id(user_id: int):

    connection = get_db_connection()

    try:
        user = connection.execute(
            "SELECT id, email, role FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()

        return dict(user) if user else None

    finally:
        connection.close()


def set_user_role(email: str, role: str):

    if role not in ASSIGNABLE_ROLES:
        raise ValueError("Only employee and HR admin roles can be assigned.")

    connection = get_db_connection()

    try:
        cursor = connection.execute(
            "UPDATE users SET role = ? WHERE email = ?",
            (role, email.strip().lower())
        )

        connection.commit()

        return cursor.rowcount > 0

    finally:
        connection.close()


# ---------------------------------
# VERIFY JWT TOKEN
# ---------------------------------

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):

    if credentials is None:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Please log in first.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    token = credentials.credentials

    try:

        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM]
        )

        user_id = int(payload["sub"])

    except (jwt.InvalidTokenError, KeyError, ValueError):

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired login token.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    user = get_user_by_id(user_id)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired login token.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    return user


def require_roles(*allowed_roles: str):

    if not allowed_roles or any(
        role not in USER_ROLES
        for role in allowed_roles
    ):
        raise ValueError("At least one valid role is required.")

    def role_required(
        current_user: dict = Depends(get_current_user)
    ):
        if current_user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource."
            )

        return current_user

    return role_required


# Initialize database when this module loads
initialize_database()
