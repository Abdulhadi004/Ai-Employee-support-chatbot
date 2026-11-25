import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def send_verification_email(email: str, token: str):
    base_url = os.getenv("APP_BASE_URL", "").strip().rstrip("/")
    parsed_base_url = urlsplit(base_url)
    if (
        parsed_base_url.scheme not in {"http", "https"}
        or not parsed_base_url.netloc
        or parsed_base_url.path
        or parsed_base_url.query
        or parsed_base_url.fragment
    ):
        raise RuntimeError(
            "Set APP_BASE_URL to the public HTTP or HTTPS application origin."
        )

    host = os.getenv("SMTP_HOST", "").strip()
    sender = os.getenv("SMTP_FROM_EMAIL", "").strip()
    if not host or not sender:
        raise RuntimeError(
            "Set SMTP_HOST and SMTP_FROM_EMAIL to enable email verification."
        )

    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    if bool(username) != bool(password):
        raise RuntimeError(
            "Set both SMTP_USERNAME and SMTP_PASSWORD, or leave both unset."
        )

    security_mode = os.getenv("SMTP_SECURITY", "starttls").strip().lower()
    if security_mode not in {"starttls", "ssl", "none"}:
        raise RuntimeError("SMTP_SECURITY must be starttls, ssl, or none.")

    port = int(os.getenv("SMTP_PORT", "587"))
    timeout = float(os.getenv("SMTP_TIMEOUT_SECONDS", "15"))
    if port < 1 or port > 65535 or timeout <= 0:
        raise RuntimeError("SMTP_PORT and SMTP_TIMEOUT_SECONDS are invalid.")

    link = f"{base_url}/verify-email?{urlencode({'token': token})}"
    message = EmailMessage()
    message["Subject"] = "Verify your employee account"
    message["From"] = sender
    message["To"] = email
    message.set_content(
        "Hello,\n\n"
        "Verify your email address to continue with your employee registration:\n"
        f"{link}\n\n"
        "This link expires in 24 hours. If you did not create this account, "
        "you can ignore this message.\n"
    )

    if security_mode == "ssl":
        smtp_connection = smtplib.SMTP_SSL(
            host,
            port,
            timeout=timeout,
            context=ssl.create_default_context()
        )
    else:
        smtp_connection = smtplib.SMTP(host, port, timeout=timeout)

    with smtp_connection as smtp:
        if security_mode == "starttls":
            smtp.starttls(context=ssl.create_default_context())
        if username:
            smtp.login(username, password)
        smtp.send_message(message)
