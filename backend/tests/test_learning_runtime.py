import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend.learning_space_api import get_learning_runtime, update_learning_runtime
from backend.models import (
    CardSection,
    KnowledgeCard,
    LearningRuntimeRecord,
    LearningSpace,
    User,
)
from backend.schemas import LearningNavigationEntry, UpdateLearningRuntimeRequest


class LearningRuntimeBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(cls.engine)
        cls.engine.dispose()

    def setUp(self):
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        owner = User(id="runtime-owner", username="runtime-owner", password_hash="hash")
        other = User(id="runtime-other", username="runtime-other", password_hash="hash")
        self.space = LearningSpace(
            id="runtime-space", user_id=owner.id, title="space", learning_goal="goal"
        )
        self.other_space = LearningSpace(
            id="runtime-other-space", user_id=other.id, title="other", learning_goal="goal"
        )
        self.card = KnowledgeCard(
            id="runtime-card", space_id=self.space.id, title="card", status="active"
        )
        self.other_card = KnowledgeCard(
            id="runtime-other-card",
            space_id=self.other_space.id,
            title="other card",
            status="active",
        )
        self.section = CardSection(id="runtime-section", card_id=self.card.id, title="section")
        self.other_section = CardSection(
            id="runtime-other-section", card_id=self.other_card.id, title="other section"
        )
        self.db.add_all([owner, other])
        self.db.flush()
        self.db.add_all([self.space, self.other_space])
        self.db.flush()
        self.db.add_all([self.card, self.other_card])
        self.db.flush()
        self.db.add_all([self.section, self.other_section])
        self.db.commit()
        self.owner_id = owner.id

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def payload(self, *, card_id=None, section_id=None, stack=None, event_type="navigation"):
        return UpdateLearningRuntimeRequest(
            currentCardId=card_id or self.card.id,
            currentSectionId=section_id,
            navigationStack=stack or [],
            eventType=event_type,
        )

    def call_update(self, payload):
        with patch("backend.services.ownership.current_user_id", return_value=self.owner_id):
            return update_learning_runtime(self.space.id, payload, self.db)

    def test_first_update_creates_runtime_and_records_sequence_one(self):
        runtime = self.call_update(
            self.payload(
                section_id=self.section.id,
                stack=[LearningNavigationEntry(cardId=self.card.id, sectionId=self.section.id)],
                event_type="open",
            )
        )

        self.assertEqual(runtime.space_id, self.space.id)
        self.assertEqual(runtime.current_card_id, self.card.id)
        self.assertEqual(runtime.current_section_id, self.section.id)
        self.assertEqual(runtime.source_card_id, self.card.id)
        self.assertEqual(runtime.source_section_id, self.section.id)
        self.assertEqual(
            runtime.navigation_stack,
            [{"cardId": self.card.id, "sectionId": self.section.id}],
        )
        record = self.db.scalar(select(LearningRuntimeRecord))
        self.assertEqual(record.seq, 1)
        self.assertEqual(record.event_type, "open")
        self.assertEqual(
            json.loads(record.payload_json)["navigationStack"][0]["cardId"],
            self.card.id,
        )

    def test_following_updates_increment_record_sequence(self):
        self.call_update(self.payload(section_id=self.section.id))
        self.call_update(self.payload(event_type="next"))

        records = list(
            self.db.scalars(select(LearningRuntimeRecord).order_by(LearningRuntimeRecord.seq))
        )
        self.assertEqual([record.seq for record in records], [1, 2])
        self.assertEqual(records[1].event_type, "next")

        with patch("backend.services.ownership.current_user_id", return_value=self.owner_id):
            self.assertIsNotNone(get_learning_runtime(self.space.id, self.db))

    def assert_bad_update(self, payload, detail):
        with self.assertRaises(HTTPException) as caught:
            self.call_update(payload)
        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(caught.exception.detail, detail)
        self.assertEqual(self.db.scalar(select(LearningRuntimeRecord)), None)

    def test_rejects_current_card_and_section_outside_space_or_card(self):
        self.assert_bad_update(
            self.payload(card_id=self.other_card.id),
            "Current card does not belong to this learning space",
        )
        self.assert_bad_update(
            self.payload(section_id=self.other_section.id),
            "Current section does not belong to current card",
        )

    def test_rejects_invalid_navigation_stack_card_and_section(self):
        self.assert_bad_update(
            self.payload(stack=[LearningNavigationEntry(cardId=self.other_card.id)]),
            "Navigation stack contains an invalid card",
        )
        self.assert_bad_update(
            self.payload(
                stack=[
                    LearningNavigationEntry(
                        cardId=self.card.id,
                        sectionId=self.other_section.id,
                    )
                ]
            ),
            "Navigation stack contains an invalid section",
        )

    def test_cross_user_space_is_not_found_for_get_and_put(self):
        with patch("backend.services.ownership.current_user_id", return_value=self.owner_id):
            with self.assertRaises(HTTPException) as get_error:
                get_learning_runtime(self.other_space.id, self.db)
            self.assertEqual(get_error.exception.status_code, 404)
            with self.assertRaises(HTTPException) as put_error:
                update_learning_runtime(
                    self.other_space.id,
                    self.payload(),
                    self.db,
                )
            self.assertEqual(put_error.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
