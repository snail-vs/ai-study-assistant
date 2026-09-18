import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from backend import api
from backend.models import (
    DefaultModelPreference,
    ProviderCredential,
    TaskModelRoute,
)


class _ScalarResult:
    def __init__(self, values):
        self._values = list(values)

    def __iter__(self):
        return iter(self._values)

    def all(self):
        return list(self._values)


class _SessionDouble:
    """Small query-aware Session double; no engine or persistent DB is used."""

    def __init__(self, credentials=(), routes=(), preference=None):
        self.credentials = list(credentials)
        self.routes = list(routes)
        self.preference = preference
        self.added = []
        self.deleted = []

    def scalars(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        if entity is ProviderCredential:
            return _ScalarResult([item for item in self.credentials if item.user_id == "user-a"])
        if entity is TaskModelRoute:
            return _ScalarResult([item for item in self.routes if item.user_id == "user-a"])
        raise AssertionError(f"unexpected query entity: {entity!r}")

    def scalar(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        if entity is DefaultModelPreference:
            return self.preference
        if entity is ProviderCredential:
            return next((item for item in self.credentials if item.user_id == "user-a" and item.is_active), None)
        raise AssertionError(f"unexpected scalar query entity: {entity!r}")

    def get(self, entity, identity):
        if entity is ProviderCredential:
            user_id, provider_name = identity
            return next(
                (item for item in self.credentials if item.user_id == user_id and item.provider_name == provider_name),
                None,
            )
        raise AssertionError(f"unexpected get entity: {entity!r}")

    def add(self, value):
        self.added.append(value)

    def delete(self, value):
        self.deleted.append(value)


def _credential(user_id, provider, models, *, active_model=None, is_active=False, api_key="secret"):
    return ProviderCredential(
        user_id=user_id,
        provider_name=provider,
        models_json=json.dumps(models),
        active_model=active_model,
        is_active=is_active,
        api_key_ciphertext=f"ciphertext-{api_key}",
        api_key_nonce="nonce",
    )


class ProviderSettingsTests(unittest.TestCase):
    def setUp(self):
        self.user_id = "user-a"
        self.user_patch = patch.object(api, "current_user_id", return_value=self.user_id)
        self.user_patch.start()
        self.addCleanup(self.user_patch.stop)

    def test_provider_settings_is_user_scoped_and_never_exposes_credentials(self):
        db = _SessionDouble(
            credentials=[
                _credential(self.user_id, "deepseek", ["deepseek-chat"], active_model="deepseek-chat", is_active=True),
                _credential("user-b", "openrouter", ["private-model"], active_model="private-model", is_active=True),
            ],
            routes=[
                TaskModelRoute(user_id=self.user_id, task="side_agent", provider_name="deepseek", model_id="deepseek-chat"),
                TaskModelRoute(user_id="user-b", task="teacher_guidance", provider_name="openrouter", model_id="private-model"),
            ],
        )

        with patch.dict(api.provider_state, {"providers": {"deepseek": False, "openrouter": False}}, clear=False):
            result = api.provider_settings(db)

        self.assertEqual(result["activeProvider"], "deepseek")
        self.assertEqual(result["activeModel"], "deepseek-chat")
        self.assertEqual(result["models"], {"deepseek": ["deepseek-chat"], "openrouter": []})
        self.assertEqual(result["taskRoutes"], {
            "side_answer": "deepseek:deepseek-chat",
            "gap_diagnosis": "deepseek:deepseek-chat",
        })
        rendered = repr(result)
        self.assertNotIn("ciphertext-secret", rendered)
        self.assertNotIn("nonce", rendered)

    def test_provider_settings_preference_wins_over_active_credential(self):
        credential = _credential(self.user_id, "deepseek", ["m1", "m2"], active_model="m1", is_active=True)
        preference = DefaultModelPreference(user_id=self.user_id, provider_name="deepseek", model_id="m2")
        result = api.provider_settings(_SessionDouble(credentials=[credential], preference=preference))
        self.assertEqual(result["activeProvider"], "deepseek")
        self.assertEqual(result["activeModel"], "m2")

    def test_validate_task_routes_rejects_unknown_task_provider_and_model(self):
        db = _SessionDouble(credentials=[_credential(self.user_id, "deepseek", ["m1"])])
        cases = [
            ({"not-a-task": "deepseek:m1"}, "Unknown task route"),
            ({"teacher_guidance": "missing-separator"}, "Invalid task model"),
            ({"teacher_guidance": "openrouter:m1"}, "Invalid task model"),
            ({"teacher_guidance": "deepseek:not-selected"}, "Model is not selected"),
        ]
        for routes, expected in cases:
            with self.subTest(routes=routes), self.assertRaises(HTTPException) as raised:
                api.validate_task_routes(routes, db)
            self.assertIn(expected, raised.exception.detail)

    def test_validate_task_routes_accepts_selected_model(self):
        db = _SessionDouble(credentials=[_credential(self.user_id, "deepseek", ["m1"])])
        api.validate_task_routes({"teacher_guidance": "deepseek:m1"}, db)

    def test_save_task_routes_upserts_and_deletes_stale_routes_for_current_user(self):
        existing = TaskModelRoute(user_id=self.user_id, task="teacher_guidance", provider_name="deepseek", model_id="old")
        stale = TaskModelRoute(user_id=self.user_id, task="quiz_generation", provider_name="deepseek", model_id="m1")
        other_user = TaskModelRoute(user_id="user-b", task="teacher_guidance", provider_name="deepseek", model_id="m1")
        db = _SessionDouble(
            credentials=[_credential(self.user_id, "deepseek", ["m1", "m2"])],
            routes=[existing, stale, other_user],
        )

        api.save_task_routes({"teacher_guidance": "deepseek:m2"}, db)

        self.assertIs(db.added[0], existing)
        self.assertEqual((existing.provider_name, existing.model_id), ("deepseek", "m2"))
        self.assertEqual(db.deleted, [stale])
        self.assertIsNot(db.added[0], other_user)


if __name__ == "__main__":
    unittest.main()
