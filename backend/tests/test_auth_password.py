import hashlib
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from backend import auth_api
from backend.db import Base, get_db
from backend.main import (
    http_exception_handler,
    request_id_middleware,
    validation_exception_handler,
)
from backend.models import AuthSession, User
from backend.security.auth import SESSION_COOKIE, hash_password


AUTH_PATH = "/api/v1/auth"
USER_ID = "password-user"
OTHER_USER_ID = "other-password-user"
OLD_PASSWORD = "old-password"
NEW_PASSWORD = "replacement-password"


class AuthPasswordTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        database = Path(directory.name) / "auth.sqlite3"
        self.engine = create_engine(
            f"sqlite:///{database}",
            connect_args={"check_same_thread": False, "timeout": 10},
        )
        self.addCleanup(self.engine.dispose)

        @event.listens_for(self.engine, "connect")
        def configure_sqlite(connection, _record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(self.engine, tables=[User.__table__, AuthSession.__table__])
        with Session(self.engine) as db:
            db.add_all([
                User(id=USER_ID, username="password-user", password_hash=hash_password(OLD_PASSWORD)),
                User(
                    id=OTHER_USER_ID,
                    username="other-user",
                    password_hash=hash_password("other-password"),
                ),
            ])
            db.commit()

        # Use the production routes and error envelope without application startup,
        # whose course-generation recovery uses the production database directly.
        self.app = FastAPI()
        self.app.include_router(auth_api.router, prefix="/api/v1")
        self.app.add_exception_handler(HTTPException, http_exception_handler)
        self.app.add_exception_handler(RequestValidationError, validation_exception_handler)
        self.app.middleware("http")(request_id_middleware)

        def isolated_db():
            with Session(self.engine, autoflush=False) as db:
                yield db

        self.app.dependency_overrides[get_db] = isolated_db
        self.observer = self._client()

    def _client(self):
        client = TestClient(
            self.app, base_url="https://testserver", raise_server_exceptions=False
        )
        self.addCleanup(client.close)
        return client

    def _login_client(self, password=OLD_PASSWORD, username="password-user"):
        client = self._client()
        response = client.post(
            f"{AUTH_PATH}/login", json={"username": username, "password": password}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["username"], username)
        self.assertIsNotNone(client.cookies.get(SESSION_COOKIE))
        return client

    def _assert_login_rejected(self, password):
        response = self._client().post(
            f"{AUTH_PATH}/login", json={"username": "password-user", "password": password}
        )
        self.assertEqual(response.status_code, 401, response.text)
        self.assertNotIn("set-cookie", response.headers)

    def _assert_session(self, token, status=200, user_id=USER_ID):
        response = self.observer.get(
            f"{AUTH_PATH}/me", headers={"Cookie": f"{SESSION_COOKIE}={token}"}
        )
        self.assertEqual(response.status_code, status, response.text)
        if status == 200:
            self.assertEqual(response.json()["id"], user_id)

    def _snapshot(self):
        with Session(self.engine) as db:
            return {
                "passwords": dict(db.execute(select(User.id, User.password_hash)).all()),
                "sessions": tuple(db.execute(
                    select(
                        AuthSession.id,
                        AuthSession.user_id,
                        AuthSession.token_hash,
                        AuthSession.expires_at,
                        AuthSession.created_at,
                        AuthSession.last_seen_at,
                    ).order_by(AuthSession.id)
                ).all()),
            }

    def _assert_only_session(self, token):
        with Session(self.engine) as db:
            hashes = db.scalars(
                select(AuthSession.token_hash).where(AuthSession.user_id == USER_ID)
            ).all()
        self.assertEqual(hashes, [hashlib.sha256(token.encode()).hexdigest()])

    def _assert_rejected(self, client, payload, status, message=None):
        before = self._snapshot()
        token = client.cookies.get(SESSION_COOKIE)
        response = client.post(f"{AUTH_PATH}/password", json=payload)
        self.assertEqual(response.status_code, status, response.text)
        self.assertNotIn("set-cookie", response.headers)
        self.assertEqual(client.cookies.get(SESSION_COOKIE), token)
        self.assertEqual(self._snapshot(), before)
        error = response.json()["error"]
        self.assertEqual(error["code"], "VALIDATION_ERROR" if status == 422 else "HTTP_ERROR")
        if message is not None:
            self.assertEqual(error["message"], message)
        if token:
            self._assert_session(token)

    def test_change_rotates_cookie_revokes_old_sessions_and_preserves_other_user(self):
        current = self._login_client()
        secondary = self._login_client()
        other = self._login_client(password="other-password", username="other-user")
        old_tokens = [current.cookies.get(SESSION_COOKIE), secondary.cookies.get(SESSION_COOKIE)]
        other_token = other.cookies.get(SESSION_COOKIE)
        before = self._snapshot()

        response = current.post(
            f"{AUTH_PATH}/password",
            json={"currentPassword": OLD_PASSWORD, "newPassword": NEW_PASSWORD},
        )

        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(response.content, b"")
        new_token = current.cookies.get(SESSION_COOKIE)
        self.assertNotIn(new_token, old_tokens)
        cookie = response.headers["set-cookie"].lower()
        for attribute in ("httponly", "samesite=lax", "path=/", "max-age="):
            self.assertIn(attribute, cookie)
        self._assert_session(new_token)
        self._assert_only_session(new_token)
        for token in old_tokens:
            self._assert_session(token, 401)
        self._assert_session(other_token, user_id=OTHER_USER_ID)
        after = self._snapshot()
        self.assertNotEqual(after["passwords"][USER_ID], before["passwords"][USER_ID])
        self.assertEqual(after["passwords"][OTHER_USER_ID], before["passwords"][OTHER_USER_ID])
        self.assertEqual(
            [row for row in after["sessions"] if row[1] == OTHER_USER_ID],
            [row for row in before["sessions"] if row[1] == OTHER_USER_ID],
        )
        self._assert_login_rejected(OLD_PASSWORD)
        self._login_client(password=NEW_PASSWORD)
        self._login_client(password="other-password", username="other-user")

    def test_unauthenticated_change_preserves_passwords_and_sessions(self):
        current = self._login_client()
        other = self._login_client(password="other-password", username="other-user")
        self._assert_rejected(
            self._client(),
            {"currentPassword": OLD_PASSWORD, "newPassword": NEW_PASSWORD},
            401,
            "请先登录",
        )
        self._assert_session(current.cookies.get(SESSION_COOKIE))
        self._assert_session(other.cookies.get(SESSION_COOKIE), user_id=OTHER_USER_ID)
        self._assert_login_rejected(NEW_PASSWORD)
        self._login_client()

    def test_wrong_current_and_identical_password_leave_credentials_and_sessions_unchanged(self):
        current = self._login_client()
        secondary = self._login_client()
        for old, new, message in (
            ("incorrect-current", NEW_PASSWORD, "当前密码不正确"),
            (OLD_PASSWORD, OLD_PASSWORD, "新密码不能与当前密码相同"),
        ):
            with self.subTest(current=old, new=new):
                self._assert_rejected(
                    current, {"currentPassword": old, "newPassword": new}, 400, message
                )
                self._assert_session(secondary.cookies.get(SESSION_COOKIE))
        self._assert_login_rejected(NEW_PASSWORD)
        self._login_client()

    def test_invalid_length_boundaries_do_not_change_password_or_sessions(self):
        current = self._login_client()
        secondary = self._login_client()
        for field, value in (
            ("currentPassword", ""),
            ("currentPassword", "x" * 201),
            ("newPassword", "x" * 7),
            ("newPassword", "x" * 201),
        ):
            with self.subTest(field=field, length=len(value)):
                payload = {"currentPassword": OLD_PASSWORD, "newPassword": NEW_PASSWORD}
                payload[field] = value
                self._assert_rejected(current, payload, 422, "请求参数校验失败")
                self._assert_session(secondary.cookies.get(SESSION_COOKIE))
        self._assert_login_rejected(NEW_PASSWORD)
        self._login_client()

    def test_valid_length_boundaries_are_accepted(self):
        # Login allows legacy one-character passwords even though registration
        # requires eight; changing them must still accept the current password.
        with Session(self.engine) as db:
            db.get(User, USER_ID).password_hash = hash_password("x")
            db.commit()
        current = self._login_client(password="x")
        for old, new in (("x", "n" * 8), ("n" * 8, "m" * 200), ("m" * 200, NEW_PASSWORD)):
            with self.subTest(current_length=len(old), new_length=len(new)):
                token = current.cookies.get(SESSION_COOKIE)
                response = current.post(
                    f"{AUTH_PATH}/password", json={"currentPassword": old, "newPassword": new}
                )
                self.assertEqual(response.status_code, 204, response.text)
                self._assert_session(token, 401)
                self._assert_session(current.cookies.get(SESSION_COOKIE))
                self._assert_only_session(current.cookies.get(SESSION_COOKIE))
                self._assert_login_rejected(old)
                self._login_client(password=new)

    def test_password_whitespace_and_unicode_are_not_trimmed(self):
        current = self._login_client()
        exact_password = "  new 密码  "
        response = current.post(
            f"{AUTH_PATH}/password",
            json={"currentPassword": OLD_PASSWORD, "newPassword": exact_password},
        )
        self.assertEqual(response.status_code, 204, response.text)
        self._assert_login_rejected(exact_password.strip())
        self._login_client(password=exact_password)
        response = current.post(
            f"{AUTH_PATH}/password",
            json={"currentPassword": exact_password, "newPassword": NEW_PASSWORD},
        )
        self.assertEqual(response.status_code, 204, response.text)
        self._assert_login_rejected(exact_password)
        self._login_client(password=NEW_PASSWORD)

    def test_session_insert_failure_rolls_back_password_and_revocation(self):
        current = self._login_client()
        secondary = self._login_client()
        before = self._snapshot()
        token = current.cookies.get(SESSION_COOKIE)
        with self.engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TRIGGER reject_auth_session BEFORE INSERT ON auth_sessions "
                "BEGIN SELECT RAISE(ABORT, 'session write rejected'); END"
            )

        response = current.post(
            f"{AUTH_PATH}/password",
            json={"currentPassword": OLD_PASSWORD, "newPassword": NEW_PASSWORD},
        )

        self.assertEqual(response.status_code, 500, response.text)
        self.assertNotIn("set-cookie", response.headers)
        self.assertEqual(current.cookies.get(SESSION_COOKIE), token)
        self.assertEqual(self._snapshot(), before)
        self._assert_session(token)
        self._assert_session(secondary.cookies.get(SESSION_COOKIE))
        with self.engine.begin() as connection:
            connection.exec_driver_sql("DROP TRIGGER reject_auth_session")
        self._assert_login_rejected(NEW_PASSWORD)
        self._login_client()

    def test_concurrent_changes_only_keep_the_winning_password_and_session(self):
        clients = [self._login_client(), self._login_client()]
        old_tokens = [client.cookies.get(SESSION_COOKIE) for client in clients]
        passwords = ["first-replacement", "second-replacement"]
        barrier = threading.Barrier(2)
        verify = auth_api.verify_password

        def simultaneous_verify(password, encoded):
            result = verify(password, encoded)
            barrier.wait(timeout=10)
            return result

        with patch.object(auth_api, "verify_password", side_effect=simultaneous_verify):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(
                        client.post,
                        f"{AUTH_PATH}/password",
                        json={"currentPassword": OLD_PASSWORD, "newPassword": password},
                    )
                    for client, password in zip(clients, passwords)
                ]
                responses = [future.result(timeout=30) for future in futures]

        self.assertEqual(sorted(response.status_code for response in responses), [204, 400])
        winner = next(index for index, response in enumerate(responses) if response.status_code == 204)
        loser = 1 - winner
        self.assertNotIn("set-cookie", responses[loser].headers)
        self.assertEqual(clients[loser].cookies.get(SESSION_COOKIE), old_tokens[loser])
        token = clients[winner].cookies.get(SESSION_COOKIE)
        self._assert_only_session(token)
        self._assert_session(token)
        for old_token in old_tokens:
            self._assert_session(old_token, 401)
        self._assert_login_rejected(OLD_PASSWORD)
        self._assert_login_rejected(passwords[loser])
        self._login_client(password=passwords[winner])

    def test_login_verified_before_password_change_cannot_create_a_stale_session(self):
        current = self._login_client()
        old_token = current.cookies.get(SESSION_COOKIE)
        stale_login = self._client()
        verified = threading.Event()
        release = threading.Event()
        verify = auth_api.verify_password

        def pause_first_verification(password, encoded):
            result = verify(password, encoded)
            if not verified.is_set():
                verified.set()
                if not release.wait(timeout=10):
                    raise RuntimeError("password-change request did not finish")
            return result

        with patch.object(auth_api, "verify_password", side_effect=pause_first_verification):
            with ThreadPoolExecutor(max_workers=1) as executor:
                pending_login = executor.submit(
                    stale_login.post,
                    f"{AUTH_PATH}/login",
                    json={"username": "password-user", "password": OLD_PASSWORD},
                )
                try:
                    self.assertTrue(verified.wait(timeout=10))
                    changed = current.post(
                        f"{AUTH_PATH}/password",
                        json={"currentPassword": OLD_PASSWORD, "newPassword": NEW_PASSWORD},
                    )
                    self.assertEqual(changed.status_code, 204, changed.text)
                finally:
                    release.set()
                rejected = pending_login.result(timeout=30)

        self.assertEqual(rejected.status_code, 401, rejected.text)
        self.assertNotIn("set-cookie", rejected.headers)
        self.assertIsNone(stale_login.cookies.get(SESSION_COOKIE))
        token = current.cookies.get(SESSION_COOKIE)
        self._assert_only_session(token)
        self._assert_session(token)
        self._assert_session(old_token, 401)
        self._assert_login_rejected(OLD_PASSWORD)
        self._login_client(password=NEW_PASSWORD)


if __name__ == "__main__":
    unittest.main()
