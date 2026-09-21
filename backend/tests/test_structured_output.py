import unittest

from pydantic import ValidationError

from backend.agents.schemas import CourseOutlineDraft, CourseOutlineRevisionDraft
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


if __name__ == "__main__":
    unittest.main()
