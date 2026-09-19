import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend import api
from backend.conversation_api import router as conversation_router
from backend.conversation_api import create_conversation, list_conversations
from backend.db import Base
from backend.main import app
from backend.models import CardSection, Conversation, KnowledgeCard, LearningSpace, User
from backend.schemas import (
    AIRunResponse,
    ConversationResponse,
    CreateConversationRequest,
    MessageResponse,
)
from backend.security.auth import require_current_user


def _route_entries(router, prefix=""):
    """Walk included routers without losing duplicate route registrations."""
    entries = []
    for route in router.routes:
        child = getattr(route, "original_router", None)
        if child is not None:
            include_prefix = getattr(getattr(route, "include_context", None), "prefix", "")
            entries.extend(_route_entries(child, prefix + include_prefix))
            continue
        path = prefix + route.path
        methods = sorted(method.upper() for method in (route.methods or set()))
        if methods:
            entries.extend((method, path, route) for method in methods)
    return entries


class ConversationApiContractTests(unittest.TestCase):
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
        self.db = Session(self.engine)
        self.user = User(id="conversation-user", username="conversation-user", password_hash="hash")
        self.space = LearningSpace(
            id="conversation-space", user_id=self.user.id, title="Space", learning_goal="Goal"
        )
        self.card = KnowledgeCard(id="conversation-card", space_id=self.space.id, title="Card")
        self.section = CardSection(id="conversation-section", card_id=self.card.id, title="Section")
        self.other_section = CardSection(
            id="conversation-other-section", card_id=self.card.id, title="Other section"
        )
        self.db.add_all([self.user, self.space, self.card, self.section, self.other_section])
        self.db.commit()

    def tearDown(self):
        self.db.rollback()
        self.db.close()
        with Session(self.engine) as db:
            db.query(Conversation).delete()
            db.query(CardSection).delete()
            db.query(KnowledgeCard).delete()
            db.query(LearningSpace).delete()
            db.query(User).delete()
            db.commit()

    def test_router_owns_exact_conversation_routes(self):
        expected = {
            ("POST", "/cards/{card_id}/conversations"),
            ("GET", "/cards/{card_id}/conversations"),
            ("GET", "/conversations/{conversation_id}/messages"),
            ("GET", "/conversations/{conversation_id}/runs/active"),
            ("POST", "/conversations/{conversation_id}/messages/stream"),
        }
        actual = [
            (method, route.path)
            for method, path, route in _route_entries(conversation_router)
        ]
        self.assertEqual(set(actual), expected)
        self.assertEqual(len(actual), len(set(actual)))

    def test_route_status_and_response_contracts_are_explicit(self):
        routes = {
            (method, route.path): route
            for method, _path, route in _route_entries(conversation_router)
        }
        self.assertEqual(
            routes[("POST", "/cards/{card_id}/conversations")].response_model,
            ConversationResponse,
        )
        self.assertEqual(
            routes[("GET", "/cards/{card_id}/conversations")].response_model,
            list[ConversationResponse],
        )
        self.assertEqual(
            routes[("GET", "/conversations/{conversation_id}/messages")].response_model,
            list[MessageResponse],
        )
        self.assertEqual(
            routes[("GET", "/conversations/{conversation_id}/runs/active")].response_model,
            AIRunResponse | None,
        )
        self.assertIsNone(
            routes[("POST", "/conversations/{conversation_id}/messages/stream")].response_model
        )
        self.assertEqual(routes[("POST", "/cards/{card_id}/conversations")].status_code, 201)
        for key, route in routes.items():
            if key != ("POST", "/cards/{card_id}/conversations"):
                self.assertEqual(route.status_code or 200, 200)

    def test_conversation_routes_are_registered_once_in_application(self):
        entries = [
            (method, path)
            for method, path, _route in _route_entries(app.router)
            if path.startswith("/api/v1/conversations/")
            or path == "/api/v1/cards/{card_id}/conversations"
        ]
        expected = [
            ("GET", "/api/v1/cards/{card_id}/conversations"),
            ("POST", "/api/v1/cards/{card_id}/conversations"),
            ("GET", "/api/v1/conversations/{conversation_id}/messages"),
            ("GET", "/api/v1/conversations/{conversation_id}/runs/active"),
            ("POST", "/api/v1/conversations/{conversation_id}/messages/stream"),
        ]
        self.assertEqual(sorted(entries), sorted(expected))
        self.assertEqual(len(entries), len(set(entries)))

    def test_conversation_router_requires_current_user_for_each_route(self):
        self.assertTrue(conversation_router.dependencies)
        self.assertTrue(
            any(
                getattr(dependency, "dependency", None) is require_current_user
                for dependency in conversation_router.dependencies
            )
        )
        for route in conversation_router.routes:
            self.assertTrue(
                any(
                    dependency.dependency is require_current_user
                    for dependency in route.dependencies
                ),
                route.path,
            )

    def test_legacy_router_no_longer_owns_conversation_routes(self):
        paths = {
            route.path
            for route in api.router.routes
            if route.path.startswith("/cards/") and route.path.endswith("/conversations")
        }
        self.assertEqual(paths, set())
        paths = {
            route.path
            for route in api.router.routes
            if route.path.startswith("/conversations/")
        }
        self.assertEqual(paths, set())

    def test_create_conversation_uses_default_participants(self):
        payload = CreateConversationRequest(
            sectionId=self.section.id,
            conversationType="main",
            title="Main discussion",
            rootQuestion="How?",
        )
        with patch("backend.services.ownership.current_user_id", return_value=self.user.id):
            conversation = create_conversation(self.card.id, payload, self.db)

        self.assertEqual(conversation.participant_ids, ["teacher"])
        self.assertEqual(conversation.section_id, self.section.id)

    def test_create_conversation_rejects_unknown_participant(self):
        payload = CreateConversationRequest(
            sectionId=self.section.id,
            conversationType="side",
            title="Side discussion",
            rootQuestion="How?",
            participantIds=["unknown-agent"],
        )
        with patch("backend.services.ownership.current_user_id", return_value=self.user.id):
            with self.assertRaises(HTTPException) as caught:
                create_conversation(self.card.id, payload, self.db)

        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(caught.exception.detail, "Unknown agent: unknown-agent")

    def test_create_conversation_rejects_missing_or_soft_deleted_card(self):
        payload = CreateConversationRequest(
            sectionId=self.section.id,
            conversationType="side",
            title="Side discussion",
            rootQuestion="How?",
        )
        with patch("backend.services.ownership.current_user_id", return_value=self.user.id):
            with self.assertRaises(HTTPException) as missing:
                create_conversation("missing-card", payload, self.db)
        self.assertEqual(
            (missing.exception.status_code, missing.exception.detail),
            (404, "Knowledge card not found"),
        )

        self.card.status = "deleted"
        self.db.commit()
        with patch("backend.services.ownership.current_user_id", return_value=self.user.id):
            with self.assertRaises(HTTPException) as deleted:
                create_conversation(self.card.id, payload, self.db)
        self.assertEqual(
            (deleted.exception.status_code, deleted.exception.detail),
            (404, "Knowledge card not found"),
        )

    def test_create_conversation_rejects_section_from_another_card(self):
        other_card = KnowledgeCard(
            id="conversation-other-card", space_id=self.space.id, title="Other card"
        )
        self.db.add(other_card)
        self.db.commit()
        other_section = CardSection(
            id="conversation-foreign-section", card_id=other_card.id, title="Foreign"
        )
        self.db.add(other_section)
        self.db.commit()
        payload = CreateConversationRequest(
            sectionId=other_section.id,
            conversationType="side",
            title="Side discussion",
            rootQuestion="How?",
        )
        with patch("backend.services.ownership.current_user_id", return_value=self.user.id):
            with self.assertRaises(HTTPException) as caught:
                create_conversation(self.card.id, payload, self.db)
        self.assertEqual(
            (caught.exception.status_code, caught.exception.detail),
            (400, "Section does not belong to this knowledge card"),
        )

    def test_list_conversations_orders_by_created_at_then_id(self):
        timestamp = datetime(2026, 9, 19, 12, 0, 0)
        self.db.add_all(
            [
                Conversation(
                    id="conversation-z", card_id=self.card.id, section_id=self.section.id,
                    conversation_type="side", title="Z", root_question="Q", created_at=timestamp,
                ),
                Conversation(
                    id="conversation-a", card_id=self.card.id, section_id=self.section.id,
                    conversation_type="side", title="A", root_question="Q", created_at=timestamp,
                ),
                Conversation(
                    id="conversation-old", card_id=self.card.id, section_id=self.section.id,
                    conversation_type="side", title="Old", root_question="Q",
                    created_at=datetime(2026, 9, 18, 12, 0, 0),
                ),
            ]
        )
        self.db.commit()
        with patch("backend.services.ownership.current_user_id", return_value=self.user.id):
            conversations = list_conversations(self.card.id, self.section.id, self.db)
        self.assertEqual(
            [item.id for item in conversations],
            ["conversation-old", "conversation-a", "conversation-z"],
        )


if __name__ == "__main__":
    unittest.main()
