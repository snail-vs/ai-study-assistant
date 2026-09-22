import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.ai.gateway import AIGateway
from backend.db import Base
from backend.models import AITaskUsage, User
from backend.services.ai_usage import usage_summary


class _Provider:
    provider_name = "test-provider"
    model = "test-model"
    last_usage = {"input_tokens": 4, "output_tokens": 6, "total_tokens": 10}

    async def structured(self, _messages, *, task, schema):
        if task == "fails":
            raise RuntimeError("provider failed")
        self.last_usage = {"input_tokens": 4, "output_tokens": 6, "total_tokens": 10}
        return {"ok": True}

    async def stream_text(self, _messages, *, task):
        yield "ok"


class AIUsageTests(unittest.IsolatedAsyncioTestCase):
    async def test_gateway_records_success_and_failure_without_prompt_content(self):
        captured = []
        gateway = AIGateway(_Provider(), user_id="user-a")
        with patch("backend.services.ai_usage.record_usage", side_effect=lambda **row: captured.append(row)):
            self.assertEqual(await gateway.structured([], task="section_summary", schema={}), {"ok": True})
            with self.assertRaisesRegex(RuntimeError, "provider failed"):
                await gateway.structured([], task="fails", schema={})
        self.assertEqual([(row["task"], row["succeeded"]) for row in captured], [("section_summary", True), ("fails", False)])
        self.assertEqual(captured[0]["total_tokens"], 10)
        self.assertNotIn("messages", captured[0])


class AIUsageSummaryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add_all([User(id="user-a", username="a", password_hash="x"), User(id="user-b", username="b", password_hash="x")])
        self.db.add_all([
            AITaskUsage(user_id="user-a", task="section_content", provider_name="quality", model_id="m1", succeeded=True, duration_ms=100, input_tokens=10, output_tokens=20, total_tokens=30),
            AITaskUsage(user_id="user-a", task="section_content", provider_name="quality", model_id="m1", succeeded=False, duration_ms=300),
            AITaskUsage(user_id="user-a", task="section_summary", provider_name="fast", model_id="m2", succeeded=True, duration_ms=50, input_tokens=2, output_tokens=3, total_tokens=5),
            AITaskUsage(user_id="user-b", task="section_content", provider_name="private", model_id="m3", succeeded=True, duration_ms=1),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)

    def test_summary_groups_routes_and_handles_missing_tokens_and_empty_history(self):
        rows = usage_summary(self.db, "user-a")
        content = next(row for row in rows if row["task"] == "section_content")
        self.assertEqual((content["calls"], content["successes"], content["failures"], content["totalTokens"]), (2, 1, 1, 30))
        self.assertEqual(content["averageDurationMs"], 200)
        self.assertEqual(usage_summary(self.db, "nobody"), [])


if __name__ == "__main__":
    unittest.main()
