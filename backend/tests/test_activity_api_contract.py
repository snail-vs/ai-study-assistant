import unittest

from backend import api
from backend.activity_api import router as activity_router
from backend.main import app
from backend.schemas import ActivityAttemptResponse, LearningActivityResponse
from backend.security.auth import require_current_user


def _route_entries(router, prefix=""):
    """Walk included routers while preserving duplicate route entries."""
    entries = []
    for route in router.routes:
        child = getattr(route, "original_router", None)
        if child is not None:
            context = getattr(route, "include_context", None)
            include_prefix = getattr(context, "prefix", "")
            entries.extend(_route_entries(child, prefix + include_prefix))
            continue
        methods = sorted(method.upper() for method in (route.methods or set()))
        entries.extend((method, prefix + route.path, route) for method in methods)
    return entries


class ActivityApiContractTests(unittest.TestCase):
    expected = {
        ("GET", "/cards/{card_id}/sections/{section_id}/activities"),
        ("POST", "/cards/{card_id}/sections/{section_id}/activities/quiz"),
        ("GET", "/activities/{activity_id}"),
        ("GET", "/activities/{activity_id}/attempts/latest"),
        ("POST", "/activities/{activity_id}/attempts"),
        ("POST", "/activities/{activity_id}/attempts/{attempt_id}/follow-up"),
    }

    def test_router_owns_exact_activity_routes(self):
        actual = {
            (method, path)
            for method, path, _route in _route_entries(activity_router)
        }
        self.assertEqual(actual, self.expected)
        entries = [(method, path) for method, path, _route in _route_entries(activity_router)]
        self.assertEqual(len(entries), len(set(entries)))

    def test_route_response_models_and_statuses_match_legacy_contract(self):
        routes = {
            (method, path): route
            for method, path, route in _route_entries(activity_router)
        }
        self.assertEqual(
            routes[(
                "GET", "/cards/{card_id}/sections/{section_id}/activities"
            )].response_model,
            list[LearningActivityResponse],
        )
        self.assertEqual(
            routes[(
                "POST", "/cards/{card_id}/sections/{section_id}/activities/quiz"
            )].response_model,
            LearningActivityResponse,
        )
        self.assertEqual(
            routes[("GET", "/activities/{activity_id}")].response_model,
            LearningActivityResponse,
        )
        self.assertEqual(
            routes[("GET", "/activities/{activity_id}/attempts/latest")].response_model,
            ActivityAttemptResponse | None,
        )
        self.assertEqual(
            routes[("POST", "/activities/{activity_id}/attempts")].response_model,
            ActivityAttemptResponse,
        )
        self.assertEqual(
            routes[(
                "POST", "/activities/{activity_id}/attempts/{attempt_id}/follow-up"
            )].response_model,
            ActivityAttemptResponse,
        )
        for route in routes.values():
            self.assertEqual(route.status_code or 200, 200)

    def test_every_activity_route_requires_current_user(self):
        self.assertTrue(activity_router.dependencies)
        self.assertTrue(
            any(
                getattr(dependency, "dependency", None) is require_current_user
                for dependency in activity_router.dependencies
            )
        )
        for route in activity_router.routes:
            self.assertTrue(
                any(
                    dependency.dependency is require_current_user
                    for dependency in route.dependencies
                ),
                route.path,
            )

    def test_activity_routes_are_registered_once_in_application(self):
        actual = [
            (method, path)
            for method, path, _route in _route_entries(app.router)
            if path.startswith("/api/v1/")
            and path.removeprefix("/api/v1") in {
                route_path for _method, route_path in self.expected
            }
        ]
        expected = sorted((method, "/api/v1" + path) for method, path in self.expected)
        self.assertEqual(sorted(actual), expected)
        self.assertEqual(len(actual), len(set(actual)))

    def test_legacy_router_no_longer_owns_activity_routes(self):
        paths = {
            (method, route.path)
            for method, path, route in _route_entries(api.router)
            if path in {route_path for _method, route_path in self.expected}
        }
        self.assertEqual(paths, set())


if __name__ == "__main__":
    unittest.main()
