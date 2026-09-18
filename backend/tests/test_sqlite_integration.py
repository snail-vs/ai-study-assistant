import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend import api
from backend.db import Base
from backend.models import Conversation, KnowledgeCard, LearningSpace, User


class SQLiteOwnershipIntegrationTests(unittest.TestCase):
    """Exercise ownership queries against real SQLite joins and constraints."""

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(cls.engine, "connect")
        def enable_sqlite_integrity(dbapi_connection, _connection_record):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(cls.engine)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(cls.engine)
        cls.engine.dispose()

    def setUp(self):
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.owner = User(id="user-owner", username="owner", password_hash="hash")
        self.other_user = User(id="user-other", username="other", password_hash="hash")
        self.owner_space = LearningSpace(
            id="space-owner", user_id=self.owner.id, title="Owner space", learning_goal="test"
        )
        self.other_space = LearningSpace(
            id="space-other", user_id=self.other_user.id, title="Other space", learning_goal="test"
        )
        self.owner_card = KnowledgeCard(
            id="card-owner", space_id=self.owner_space.id, title="Owner card"
        )
        self.other_card = KnowledgeCard(
            id="card-other", space_id=self.other_space.id, title="Other card"
        )
        self.owner_conversation = Conversation(
            id="conversation-owner",
            card_id=self.owner_card.id,
            conversation_type="side_question",
            title="Owner conversation",
            root_question="Question",
        )
        self.other_conversation = Conversation(
            id="conversation-other",
            card_id=self.other_card.id,
            conversation_type="side_question",
            title="Other conversation",
            root_question="Question",
        )
        # Flush each dependency level explicitly so this fixture also works
        # with SQLite foreign_keys=ON and does not rely on insertion order.
        self.db.add_all([self.owner, self.other_user])
        self.db.flush()
        self.db.add_all([self.owner_space, self.other_space])
        self.db.flush()
        self.db.add_all([self.owner_card, self.other_card])
        self.db.flush()
        self.db.add_all([self.owner_conversation, self.other_conversation])
        self.db.commit()

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def assert_not_found(self, helper, resource_id, detail):
        with self.assertRaises(HTTPException) as caught:
            helper(self.db, resource_id)
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(caught.exception.detail, detail)

    def test_current_user_can_access_owned_space_card_and_conversation(self):
        with patch("backend.api.current_user_id", return_value=self.owner.id):
            self.assertEqual(api.owned_space(self.db, self.owner_space.id).id, self.owner_space.id)
            self.assertEqual(api.owned_card(self.db, self.owner_card.id).id, self.owner_card.id)
            self.assertEqual(
                api.owned_conversation(self.db, self.owner_conversation.id).id,
                self.owner_conversation.id,
            )

    def test_other_users_resources_and_missing_ids_are_uniformly_not_found(self):
        with patch("backend.api.current_user_id", return_value=self.owner.id):
            for helper, detail, foreign_id, missing_id in (
                (api.owned_space, "Learning space not found", self.other_space.id, "space-missing"),
                (api.owned_card, "Knowledge card not found", self.other_card.id, "card-missing"),
                (
                    api.owned_conversation,
                    "Conversation not found",
                    self.other_conversation.id,
                    "conversation-missing",
                ),
            ):
                self.assert_not_found(helper, foreign_id, detail)
                self.assert_not_found(helper, missing_id, detail)

    def test_card_and_conversation_ownership_is_enforced_by_real_association_joins(self):
        # Matching the child id is insufficient: both helpers must traverse the
        # card -> space relationship to establish the current user's ownership.
        with patch("backend.api.current_user_id", return_value=self.other_user.id):
            self.assertEqual(api.owned_card(self.db, self.other_card.id).id, self.other_card.id)
            self.assertEqual(
                api.owned_conversation(self.db, self.other_conversation.id).id,
                self.other_conversation.id,
            )

        with patch("backend.api.current_user_id", return_value=self.owner.id):
            self.assert_not_found(api.owned_card, self.other_card.id, "Knowledge card not found")
            self.assert_not_found(api.owned_conversation, self.other_conversation.id, "Conversation not found")

    def test_owned_card_includes_soft_deleted_card_current_characterization(self):
        self.owner_card.status = "deleted"
        self.owner_card.deleted_at = datetime(2026, 9, 18)
        self.db.commit()

        with patch("backend.api.current_user_id", return_value=self.owner.id):
            card = api.owned_card(self.db, self.owner_card.id)

        self.assertEqual(card.id, self.owner_card.id)
        self.assertEqual(card.status, "deleted")
        self.assertIsNotNone(card.deleted_at)


if __name__ == "__main__":
    unittest.main()
