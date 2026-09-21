import unittest

from pydantic import ValidationError

from backend.agents.schemas import CourseOutlineDraft, CourseOutlineRevisionDraft
from backend.ai.base import AIProviderError
from backend.ai.capabilities import capabilities_for_route
from backend.ai.model_routing import resolve_model_route
from backend.ai.providers.openai_compatible import OpenAICompatibleProvider


class StructuredOutputTests(unittest.TestCase):
    def test_json_mode_includes_schema_instruction(self):
        schema = CourseOutlineDraft.model_json_schema()
        messages = OpenAICompatibleProvider._json_object_messages(
            [{"role": "user", "content": "生成课程大纲"}], schema
        )

        instruction = messages[-1]["content"]
        self.assertEqual(messages[-1]["role"], "system")
        self.assertIn('"outline"', instruction)
        self.assertIn('"required": ["outline"]', instruction)
        self.assertIn('"minItems": 1', instruction)

    def test_course_outline_requires_nonempty_outline(self):
        for schema, payload in (
            (CourseOutlineDraft, {}),
            (CourseOutlineRevisionDraft, {"assistantMessage": "已更新"}),
        ):
            with self.subTest(schema=schema.__name__), self.assertRaises(ValidationError):
                schema.model_validate(payload)
            with self.subTest(schema=schema.__name__), self.assertRaises(ValidationError):
                schema.model_validate({**payload, "outline": []})

    def test_deepseek_uses_responses_json_schema_without_openai_strict_flag(self):
        route = resolve_model_route("deepseek", "https://api.deepseek.com", "deepseek-v4-pro")
        self.assertEqual(route.protocol, "openai_responses")
        self.assertEqual(route.endpoint, "https://api.deepseek.com/responses")

        provider = OpenAICompatibleProvider(
            "https://api.deepseek.com", "key", "deepseek-v4-pro", endpoint=route.endpoint,
            protocol=route.protocol, route=route,
            capabilities=capabilities_for_route(route, "deepseek"),
        )
        payload = provider._responses_payload(
            [], task="section_content", schema=CourseOutlineDraft.model_json_schema()
        )
        text_format = payload["text"]["format"]
        self.assertEqual(text_format["type"], "json_schema")
        self.assertNotIn("strict", text_format)

    def test_responses_content_rejects_incomplete_generation(self):
        with self.assertRaisesRegex(AIProviderError, "max_output_tokens"):
            OpenAICompatibleProvider._responses_content({
                "status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
            })


if __name__ == "__main__":
    unittest.main()
