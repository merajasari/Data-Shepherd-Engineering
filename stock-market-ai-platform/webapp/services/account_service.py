"""Verified member-account storage and email delivery for Data Shepherd Engineering."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
import string
from datetime import datetime, timedelta, timezone
from pathlib import Path

import resend
from werkzeug.security import check_password_hash, generate_password_hash

DB_PATH = Path(os.environ.get("MEMBER_DB_PATH", "data/live/member_accounts.db"))
TOKEN_TTL_MINUTES = 30
USERNAME_SUFFIX_DIGITS = 4
TEMP_PASSWORD_LENGTH = 16


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def initialize_account_store() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS member_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                username TEXT UNIQUE COLLATE NOCASE,
                password_hash TEXT,
                email_verified INTEGER NOT NULL DEFAULT 0,
                must_change_password INTEGER NOT NULL DEFAULT 1,
                active INTEGER NOT NULL DEFAULT 1,
                created_at_utc TEXT NOT NULL,
                verified_at_utc TEXT,
                last_login_at_utc TEXT
            );

            CREATE TABLE IF NOT EXISTS email_verifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at_utc TEXT NOT NULL,
                consumed_at_utc TEXT,
                created_at_utc TEXT NOT NULL,
                FOREIGN KEY(account_id) REFERENCES member_accounts(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_verification_account
            ON email_verifications(account_id);
            """
        )


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def valid_email(email: str) -> bool:
    return bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", normalize_email(email)))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _safe_username_base(full_name: str, email: str) -> str:
    source = full_name.strip() or email.split("@", 1)[0]
    base = re.sub(r"[^a-z0-9]", "", source.lower())[:18]
    return base or "member"


def _generate_unique_username(conn: sqlite3.Connection, full_name: str, email: str) -> str:
    base = _safe_username_base(full_name, email)
    for _ in range(100):
        suffix = f"{secrets.randbelow(10 ** USERNAME_SUFFIX_DIGITS):0{USERNAME_SUFFIX_DIGITS}d}"
        candidate = f"{base}{suffix}"
        exists = conn.execute(
            "SELECT 1 FROM member_accounts WHERE username = ? COLLATE NOCASE",
            (candidate,),
        ).fetchone()
        if not exists:
            return candidate
    raise RuntimeError("Unable to generate a unique username")


def _generate_temp_password() -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(TEMP_PASSWORD_LENGTH))
        if (
            any(c.islower() for c in password)
            and any(c.isupper() for c in password)
            and any(c.isdigit() for c in password)
            and any(c in "!@#$%" for c in password)
        ):
            return password


def begin_signup(full_name: str, email: str) -> str:
    """Create/update a pending account and return a one-time verification token."""
    initialize_account_store()
    full_name = (full_name or "").strip()
    email = normalize_email(email)
    if len(full_name) < 2:
        raise ValueError("Please enter your full name.")
    if not valid_email(email):
        raise ValueError("Please enter a valid email address.")

    token = secrets.token_urlsafe(32)
    now = _now()
    expires = now + timedelta(minutes=TOKEN_TTL_MINUTES)

    with _connect() as conn:
        account = conn.execute(
            "SELECT * FROM member_accounts WHERE email = ? COLLATE NOCASE",
            (email,),
        ).fetchone()
        if account and account["email_verified"]:
            raise ValueError("An account already exists for this email address.")

        if account:
            account_id = account["id"]
            conn.execute(
                "UPDATE member_accounts SET full_name = ? WHERE id = ?",
                (full_name, account_id),
            )
            conn.execute(
                "DELETE FROM email_verifications WHERE account_id = ? AND consumed_at_utc IS NULL",
                (account_id,),
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO member_accounts(full_name, email, created_at_utc)
                VALUES (?, ?, ?)
                """,
                (full_name, email, now.isoformat()),
            )
            account_id = cur.lastrowid

        conn.execute(
            """
            INSERT INTO email_verifications(account_id, token_hash, expires_at_utc, created_at_utc)
            VALUES (?, ?, ?, ?)
            """,
            (account_id, _token_hash(token), expires.isoformat(), now.isoformat()),
        )

    return token


def verify_email_token(token: str) -> dict:
    """Consume a verification token and issue credentials once."""
    initialize_account_store()
    now = _now()
    digest = _token_hash(token or "")

    with _connect() as conn:
        row = conn.execute(
            """
            SELECT v.*, a.full_name, a.email, a.username, a.email_verified
            FROM email_verifications v
            JOIN member_accounts a ON a.id = v.account_id
            WHERE v.token_hash = ?
            """,
            (digest,),
        ).fetchone()
        if not row:
            raise ValueError("This verification link is invalid.")
        if row["consumed_at_utc"]:
            raise ValueError("This verification link has already been used.")
        if datetime.fromisoformat(row["expires_at_utc"]) < now:
            raise ValueError("This verification link has expired. Please sign up again.")

        if row["email_verified"] and row["username"]:
            raise ValueError("This email address is already verified.")

        username = _generate_unique_username(conn, row["full_name"], row["email"])
        temp_password = _generate_temp_password()
        conn.execute(
            """
            UPDATE member_accounts
            SET username = ?, password_hash = ?, email_verified = 1,
                must_change_password = 1, verified_at_utc = ?
            WHERE id = ?
            """,
            (username, generate_password_hash(temp_password), now.isoformat(), row["account_id"]),
        )
        conn.execute(
            "UPDATE email_verifications SET consumed_at_utc = ? WHERE id = ?",
            (now.isoformat(), row["id"]),
        )

    return {
        "full_name": row["full_name"],
        "email": row["email"],
        "username": username,
        "temporary_password": temp_password,
    }


def authenticate_account(username: str, password: str) -> dict | None:
    initialize_account_store()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM member_accounts
            WHERE username = ? COLLATE NOCASE
              AND email_verified = 1
              AND active = 1
            """,
            ((username or "").strip(),),
        ).fetchone()
        if not row or not row["password_hash"]:
            return None
        if not check_password_hash(row["password_hash"], password or ""):
            return None
        conn.execute(
            "UPDATE member_accounts SET last_login_at_utc = ? WHERE id = ?",
            (_now().isoformat(), row["id"]),
        )
        return dict(row)


def change_password(account_id: int, current_password: str, new_password: str) -> None:
    initialize_account_store()
    if len(new_password or "") < 12:
        raise ValueError("New password must be at least 12 characters.")
    if not (
        any(c.islower() for c in new_password)
        and any(c.isupper() for c in new_password)
        and any(c.isdigit() for c in new_password)
    ):
        raise ValueError("Use upper-case, lower-case, and numeric characters.")

    with _connect() as conn:
        row = conn.execute(
            "SELECT password_hash FROM member_accounts WHERE id = ? AND active = 1",
            (account_id,),
        ).fetchone()
        if not row or not check_password_hash(row["password_hash"], current_password or ""):
            raise ValueError("Current password is incorrect.")
        conn.execute(
            """
            UPDATE member_accounts
            SET password_hash = ?, must_change_password = 0
            WHERE id = ?
            """,
            (generate_password_hash(new_password), account_id),
        )


def send_verification_email(recipient: str, full_name: str, verification_url: str) -> None:
    """Send the account verification email through the Resend API."""
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    from_email = os.environ.get(
        "RESEND_FROM_EMAIL",
        "accounts@datashepherdengineering.com",
    ).strip()

    if not api_key:
        raise RuntimeError("Email delivery is not configured. Set RESEND_API_KEY.")
    if not from_email:
        raise RuntimeError("Email delivery is not configured. Set RESEND_FROM_EMAIL.")

    resend.api_key = api_key
    sender = (
        from_email
        if "<" in from_email and ">" in from_email
        else f"Data Shepherd Engineering <{from_email}>"
    )

    text_body = (
        f"Hello {full_name},\n\n"
        "Thanks for signing up for Data Shepherd Engineering.\n\n"
        "Verify your email address using this secure link:\n"
        f"{verification_url}\n\n"
        f"The link expires in {TOKEN_TTL_MINUTES} minutes.\n\n"
        "After verification, we will generate your member username and a temporary password. "
        "You will be required to choose a new password on your first login.\n\n"
        "If you did not request this account, you can ignore this email.\n"
    )

    html_body = f"""
    <div style="font-family:Arial,sans-serif;max-width:620px;margin:auto;color:#172033;line-height:1.6">
      <h2 style="color:#0c405c">Verify your Data Shepherd Engineering account</h2>
      <p>Hello {full_name},</p>
      <p>Thanks for signing up for Data Shepherd Engineering.</p>
      <p style="margin:28px 0">
        <a href="{verification_url}"
           style="display:inline-block;padding:13px 20px;border-radius:8px;background:#0ca89a;color:white;text-decoration:none;font-weight:700">
          Verify email address
        </a>
      </p>
      <p>This secure link expires in <strong>{TOKEN_TTL_MINUTES} minutes</strong>.</p>
      <p>After verification, we will generate your member username and a temporary password. You will be required to choose a new password on your first login.</p>
      <p style="color:#64748b;font-size:13px">If you did not request this account, you can ignore this email.</p>
    </div>
    """

    try:
        resend.Emails.send({
            "from": sender,
            "to": [normalize_email(recipient)],
            "subject": "Verify your Data Shepherd Engineering account",
            "html": html_body,
            "text": text_body,
        })
    except Exception as exc:
        raise RuntimeError(f"Unable to send verification email: {exc}") from exc
