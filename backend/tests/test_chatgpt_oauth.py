import unittest
from unittest.mock import AsyncMock, Mock, patch

from backend.ai.oauth_chatgpt import ChatGptOAuthError, DeviceAuthorization
from backend.services import chatgpt_oauth as oauth_service


class _DbDouble:
    def __init__(self):
        self.calls = []

    def get(self, *_args):
        return None

    def scalar(self, *_args):
        return None

    def delete(self, value):
        self.calls.append(("delete", value))

    def commit(self):
        self.calls.append(("commit",))


def _credential(account_id="acct-test"):
    from backend.ai.oauth_chatgpt import ChatGptCredential

    return ChatGptCredential(
        access_token="access",
        refresh_token="refresh",
        expires_at=2_000_000_000_000,
        account_id=account_id,
    )


class ChatGptOAuthStateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        oauth_service.chatgpt_login_sessions.clear()
        self.addCleanup(oauth_service.chatgpt_login_sessions.clear)

    async def test_device_poll_success_persists_and_marks_done(self):
        session_id = "device-success"
        oauth_service.chatgpt_login_sessions[session_id] = {
            "method": "device_code",
            "status": "pending",
            "credential": None,
            "error": None,
            "user_id": "user-a",
        }
        credential = _credential()
        save = Mock()
        refresh = AsyncMock()
        await oauth_service.run_chatgpt_device_login(
            session_id,
            DeviceAuthorization("device", "code", interval_seconds=1),
            "user-a",
            poller=AsyncMock(return_value=credential),
            saver=save,
            model_refresher=refresh,
        )

        self.assertEqual(oauth_service.chatgpt_login_sessions[session_id]["status"], "done")
        self.assertIs(oauth_service.chatgpt_login_sessions[session_id]["credential"], credential)
        save.assert_called_once_with("user-a", credential)
        refresh.assert_awaited_once_with("user-a", credential)

    async def test_device_poll_failure_is_terminal_and_keeps_error_for_status(self):
        session_id = "device-failure"
        oauth_service.chatgpt_login_sessions[session_id] = {
            "method": "device_code",
            "status": "pending",
            "credential": None,
            "error": None,
            "user_id": "user-a",
        }
        await oauth_service.run_chatgpt_device_login(
            session_id,
            DeviceAuthorization("device", "code"),
            "user-a",
            poller=AsyncMock(side_effect=ChatGptOAuthError("授权被拒绝")),
        )

        self.assertEqual(oauth_service.chatgpt_login_sessions[session_id]["status"], "failed")
        self.assertEqual(
            oauth_service.chatgpt_login_sessions[session_id]["error"], "授权被拒绝"
        )

    async def test_browser_completion_saves_credential_and_cleans_session(self):
        session_id = "browser-success"
        oauth_service.chatgpt_login_sessions[session_id] = {
            "method": "browser",
            "status": "pending",
            "credential": None,
            "error": None,
            "user_id": "user-a",
            "verifier": "verifier",
            "state": "expected-state",
        }
        credential = _credential("browser-account")
        exchange = AsyncMock(return_value=credential)
        save = Mock()
        refresh = AsyncMock()
        restore = unittest.mock.Mock()
        result = await oauth_service.complete_login(
            session_id,
            "redirect",
            _DbDouble(),
            input_parser=lambda _: ("code", "expected-state"),
            code_exchanger=exchange,
            saver=save,
            model_refresher=refresh,
            provider_restorer=restore,
        )

        self.assertEqual(result["state"], "done")
        self.assertEqual(result["accountId"], "browser-account")
        self.assertNotIn(session_id, oauth_service.chatgpt_login_sessions)
        exchange.assert_awaited_once_with(
            "code", "verifier", redirect_uri="http://localhost:1455/auth/callback"
        )
        save.assert_called_once_with("user-a", credential)
        refresh.assert_awaited_once_with("user-a", credential)
        restore.assert_called_once()

    async def test_browser_completion_rejects_wrong_state_without_exchange(self):
        session_id = "browser-state-error"
        oauth_service.chatgpt_login_sessions[session_id] = {
            "method": "browser",
            "status": "pending",
            "user_id": "user-a",
            "verifier": "verifier",
            "state": "expected-state",
        }
        exchange = AsyncMock()
        result = await oauth_service.complete_login(
            session_id,
            "redirect",
            _DbDouble(),
            input_parser=lambda _: ("code", "wrong-state"),
            code_exchanger=exchange,
        )

        self.assertEqual(result["state"], "failed")
        self.assertIn("state", result["error"])
        exchange.assert_not_awaited()
        self.assertIn(session_id, oauth_service.chatgpt_login_sessions)

    def test_status_pending_done_failed_unknown_and_cleanup(self):
        pending_id = "pending"
        oauth_service.chatgpt_login_sessions[pending_id] = {"status": "pending"}
        self.assertEqual(
            oauth_service.login_status(pending_id, _DbDouble()),
            {"state": "pending"},
        )
        self.assertIn(pending_id, oauth_service.chatgpt_login_sessions)

        credential = _credential("acct-done")
        done_id = "done"
        oauth_service.chatgpt_login_sessions[done_id] = {
            "status": "done",
            "credential": credential,
            "user_id": "user-a",
        }
        restore = Mock()
        result = oauth_service.login_status(done_id, _DbDouble(), provider_restorer=restore)
        self.assertEqual(
            result,
            {"state": "done", "accountId": "acct-done", "expires": credential.expires_at},
        )
        self.assertNotIn(done_id, oauth_service.chatgpt_login_sessions)
        restore.assert_called_once()

        failed_id = "failed"
        oauth_service.chatgpt_login_sessions[failed_id] = {
            "status": "failed",
            "error": "失败原因",
        }
        result = oauth_service.login_status(failed_id, _DbDouble())
        self.assertEqual(result, {"state": "failed", "error": "失败原因"})
        self.assertNotIn(failed_id, oauth_service.chatgpt_login_sessions)

        self.assertEqual(
            oauth_service.login_status("missing", _DbDouble()),
            {"state": "unknown"},
        )

    def test_logout_refreshes_active_provider_and_returns_safe_settings(self):
        restore = Mock()
        settings = Mock(
            return_value={
                "activeProvider": "mock",
                "activeModel": None,
                "providers": {},
                "models": {},
            }
        )
        result = oauth_service.logout(
            _DbDouble(),
            user_id="user-a",
            provider_restorer=restore,
            settings_reader=settings,
        )

        self.assertEqual(result["activeProvider"], "mock")
        restore.assert_called_once()
        settings.assert_called_once()


if __name__ == "__main__":
    unittest.main()
