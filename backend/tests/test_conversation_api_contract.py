import unittest

from backend import api
from backend.conversation_api import router as conversation_router
from backend.main import app
from backend.schemas import AIRunResponse, MessageResponse
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
    def test_router_owns_exact_conversation_routes(self):
        expected = {
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
        for route in routes.values():
            self.assertEqual(route.status_code or 200, 200)

    def test_conversation_routes_are_registered_once_in_application(self):
        entries = [
            (method, path)
            for method, path, _route in _route_entries(app.router)
            if path.startswith("/api/v1/conversations/")
        ]
        expected = [
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
            if route.path.startswith("/conversations/")
        }
        self.assertEqual(paths, set())


if __name__ == "__main__":
    unittest.main()
