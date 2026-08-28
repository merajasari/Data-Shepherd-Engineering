"""Regression for member login against an existing pre-migration database."""
from __future__ import annotations

import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

os.environ.setdefault("FLASK_SECRET_KEY", "member-login-regression")

from werkzeug.security import generate_password_hash

from webapp.services import account_service


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def main() -> None:
    with TemporaryDirectory() as raw:
        database = Path(raw) / "members.db"
        account_service.DB_PATH = database

        with sqlite3.connect(database) as conn:
            conn.execute(
                """
                CREATE TABLE member_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    username TEXT UNIQUE COLLATE NOCASE,
                    password_hash TEXT,
                    email_verified INTEGER NOT NULL DEFAULT 0,
                    must_change_password INTEGER NOT NULL DEFAULT 1,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at_utc TEXT NOT NULL,
                    verified_at_utc TEXT
                )
                """
            )

        account_service.initialize_account_store()
        with sqlite3.connect(database) as conn:
            columns = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(member_accounts)"
                ).fetchall()
            }
        require(
            "last_login_at_utc" in columns,
            "Existing member database receives last-login migration",
        )

        with sqlite3.connect(database) as conn:
            conn.execute(
                """
                INSERT INTO member_accounts(
                    full_name, email, username, password_hash,
                    email_verified, must_change_password, active,
                    created_at_utc, verified_at_utc
                ) VALUES (?, ?, ?, ?, 1, 0, 1, ?, ?)
                """,
                (
                    "Regression Member",
                    "member@example.test",
                    "regression_member",
                    generate_password_hash("SafePassword123"),
                    "2026-08-01T00:00:00+00:00",
                    "2026-08-01T00:00:00+00:00",
                ),
            )

        account = account_service.authenticate_account(
            "regression_member",
            "SafePassword123",
        )
        require(account is not None, "Migrated account authenticates")
        with sqlite3.connect(database) as conn:
            last_login = conn.execute(
                """
                SELECT last_login_at_utc
                FROM member_accounts
                WHERE username = ?
                """,
                ("regression_member",),
            ).fetchone()[0]
        require(bool(last_login), "Successful login records its timestamp")

        from webapp.app import app

        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        client = app.test_client()
        response = client.post(
            "/login",
            data={
                "username": "regression_member",
                "password": "SafePassword123",
            },
            follow_redirects=False,
        )
        require(
            response.status_code == 302
            and response.headers.get("Location", "").endswith("/dashboard"),
            "Valid web login redirects without an internal server error",
        )
        rejected = client.post(
            "/login",
            data={
                "username": "regression_member",
                "password": "wrong",
            },
            follow_redirects=False,
        )
        require(
            rejected.status_code == 401,
            "Invalid password returns a controlled response",
        )

    print("Status: PASSED")
    print("Existing member database migration: VERIFIED")
    print("Login internal-server-error regression: VERIFIED")
    print("Credentials printed: NO")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
