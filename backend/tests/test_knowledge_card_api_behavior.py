import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException


class KnowledgeCardBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from backend import knowledge_card_api

        cls.module = knowledge_card_api

    def test_delete_card_is_soft_delete_and_idempotent(self):
        card = SimpleNamespace(id="card-1", status="active", deleted_at=None)
        db = MagicMock()
        with patch.object(self.module, "owned_card", return_value=card), patch.object(
            self.module, "now", return_value="deleted-at"
        ):
            result = self.module.delete_card("card-1", db)
        self.assertEqual(result, {"status": "deleted", "cardId": "card-1"})
        self.assertEqual(card.status, "deleted")
        self.assertEqual(card.deleted_at, "deleted-at")
        db.commit.assert_called_once_with()

        db.reset_mock()
        with patch.object(self.module, "owned_card", return_value=card), patch.object(
            self.module, "now", side_effect=AssertionError("must not update twice")
        ):
            self.assertEqual(self.module.delete_card("card-1", db), result)
        db.commit.assert_not_called()

    def test_guidance_creation_returns_existing_guidance_without_calling_ai(self):
        card = SimpleNamespace(id="card-1", status="active", title="Card")
        section = SimpleNamespace(
            id="section-1", card_id="card-1", title="Section", content_markdown="content"
        )
        existing = SimpleNamespace(id="guidance-1", content="existing")
        db = MagicMock()
        db.get.side_effect = [card, section]
        db.scalar.return_value = existing
        with patch.object(self.module, "owned_card", return_value=card), patch.object(
            self.module, "TeacherAgent", side_effect=AssertionError("AI must not run")
        ):
            result = asyncio.run(self.module.create_section_guidance("card-1", "section-1", db))
        self.assertIs(result, existing)
        db.add.assert_not_called()
        db.commit.assert_not_called()

    def test_accept_missing_proposal_returns_not_found(self):
        db = MagicMock()
        db.get.return_value = None
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(self.module.accept_proposal("missing", db))
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(caught.exception.detail, "Proposal not found")

    def test_accept_existing_generated_card_is_idempotent_without_ai(self):
        proposal = SimpleNamespace(id="proposal-1", card_id="card-1", generated_card_id="card-2")
        generated = SimpleNamespace(id="card-2")
        db = MagicMock()
        db.get.side_effect = [proposal, generated]
        with patch.object(
            self.module, "owned_card", return_value=SimpleNamespace(id="card-1")
        ), patch.object(
            self.module, "MainAgent", side_effect=AssertionError("AI must not run")
        ):
            result = asyncio.run(self.module.accept_proposal("proposal-1", db))
        self.assertIs(result, generated)
        db.commit.assert_not_called()

    def test_update_note_rejects_blank_content(self):
        note = SimpleNamespace(id="note-1", content="old")
        db = MagicMock()
        db.scalar.return_value = note
        with patch.object(self.module, "current_user_id", return_value="user-1"):
            with self.assertRaises(HTTPException) as caught:
                self.module.update_note(
                    "note-1", SimpleNamespace(model_dump=lambda **_: {"content": "  "}), db
                )
        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(caught.exception.detail, "Note content cannot be empty")
        db.commit.assert_not_called()

    def test_note_update_and_delete_use_user_scoped_query(self):
        note = SimpleNamespace(id="note-1", content="old", title="old title")
        db = MagicMock()
        db.scalar.return_value = note
        payload = SimpleNamespace(model_dump=lambda **_: {"content": "new", "title": "new title"})
        with patch.object(self.module, "current_user_id", return_value="user-1"):
            result = self.module.update_note("note-1", payload, db)
        self.assertIs(result, note)
        self.assertEqual(note.content, "new")
        self.assertEqual(note.title, "new title")
        db.commit.assert_called_once_with()

        db.reset_mock()
        db.scalar.return_value = note
        with patch.object(self.module, "current_user_id", return_value="user-1"):
            result = self.module.delete_note("note-1", db)
        self.assertEqual(result, {"status": "deleted", "noteId": "note-1"})
        db.delete.assert_called_once_with(note)
        db.commit.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
