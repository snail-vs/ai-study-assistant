import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend import knowledge_card_api
from backend.db import Base
from backend.models import (
    BridgeNote,
    CardSection,
    KnowledgeCard,
    LearningSpace,
    RelatedCardProposal,
    User,
)
from backend.agents.schemas import (
    BridgeNoteDraft,
    CardSectionDraft,
    KnowledgeCardDraft,
)


class RelatedCardWorkflowTests(unittest.TestCase):
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
        self.user = User(id="user-owner", username="owner", password_hash="hash")
        self.space = LearningSpace(
            id="space-owner", user_id=self.user.id, title="Owner space", learning_goal="goal"
        )
        self.source = KnowledgeCard(
            id="card-source", space_id=self.space.id, title="Source card", status="active"
        )
        self.section = CardSection(
            id="section-source", card_id=self.source.id, title="Source section", order_index=0
        )
        self.proposal = RelatedCardProposal(
            id="proposal-1",
            card_id=self.source.id,
            section_id=self.section.id,
            title="Branch topic",
            reason="Fill the prerequisite gap",
            relation_type="deep_dive",
            status="pending",
        )
        self.db.add_all([self.user, self.space])
        self.db.flush()
        self.db.add_all([self.source, self.section, self.proposal])
        self.db.commit()

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def _draft(self):
        return KnowledgeCardDraft(
            title="Generated branch",
            summary="Branch summary",
            sections=[
                CardSectionDraft(
                    title="Second section",
                    content_markdown="second",
                    content_type="practice",
                    teaching_objective="practice",
                ),
                CardSectionDraft(
                    title="First section",
                    content_markdown="first",
                    content_type="concept",
                    teaching_objective="understand",
                ),
            ],
        )

    def test_accept_persists_ordered_branch_sections_bridge_and_linkage(self):
        main = MagicMock()
        main.create_card = AsyncMock(return_value=self._draft())
        bridge = MagicMock()
        bridge.create = AsyncMock(return_value=BridgeNoteDraft(content="Connect the ideas"))
        with patch("backend.services.ownership.current_user_id", return_value=self.user.id), patch(
            "backend.services.related_card_workflow.MainAgent", return_value=main
        ), patch(
            "backend.services.related_card_workflow.BridgeAgent", return_value=bridge
        ), patch(
            "backend.services.related_card_workflow.restore_active_provider", return_value=None
        ):
            generated = asyncio.run(knowledge_card_api.accept_proposal(self.proposal.id, self.db))

        self.assertEqual(generated.title, "Generated branch")
        self.db.expire_all()
        proposal = self.db.get(RelatedCardProposal, self.proposal.id)
        card = self.db.get(KnowledgeCard, proposal.generated_card_id)
        sections = (
            self.db.query(CardSection)
            .filter(CardSection.card_id == card.id)
            .order_by(CardSection.order_index)
            .all()
        )
        bridge_note = self.db.query(BridgeNote).filter(BridgeNote.related_card_id == card.id).one()
        self.assertEqual(proposal.status, "accepted")
        self.assertEqual(proposal.generated_card_id, card.id)
        self.assertEqual([item.title for item in sections], ["Second section", "First section"])
        self.assertEqual([item.order_index for item in sections], [0, 1])
        self.assertEqual(bridge_note.card_id, self.source.id)
        self.assertEqual(bridge_note.content, "Connect the ideas")

    def test_discussion_rejects_proposal_with_invalid_section(self):
        self.proposal.section_id = "missing-section"
        self.db.commit()
        with patch("backend.services.ownership.current_user_id", return_value=self.user.id):
            with self.assertRaises(HTTPException) as caught:
                knowledge_card_api.start_proposal_discussion(self.proposal.id, self.db)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(
            caught.exception.detail,
            "Proposal is not associated with a valid course section",
        )
        self.db.refresh(self.proposal)
        self.assertEqual(self.proposal.status, "pending")

    def test_reject_enforces_ownership_and_preserves_state_on_failure(self):
        with patch("backend.services.ownership.current_user_id", return_value="other-user"):
            with self.assertRaises(HTTPException) as caught:
                knowledge_card_api.reject_proposal(self.proposal.id, self.db)
        self.assertEqual(caught.exception.status_code, 404)
        self.db.refresh(self.proposal)
        self.assertEqual(self.proposal.status, "pending")

    def test_reject_marks_owned_pending_proposal_rejected(self):
        with patch("backend.services.ownership.current_user_id", return_value=self.user.id):
            result = knowledge_card_api.reject_proposal(self.proposal.id, self.db)
        self.assertEqual(result, {"status": "rejected", "proposalId": self.proposal.id})
        self.db.refresh(self.proposal)
        self.assertEqual(self.proposal.status, "rejected")


if __name__ == "__main__":
    unittest.main()
