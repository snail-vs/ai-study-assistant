import inspect
import unittest

from backend import api, main


EXPECTED_ROUTES = {
    ("GET", "/api/v1/learning-spaces/{space_id}/cards"),
    ("POST", "/api/v1/learning-spaces/{space_id}/cards"),
    ("GET", "/api/v1/cards/{card_id}"),
    ("DELETE", "/api/v1/cards/{card_id}"),
    ("GET", "/api/v1/cards/{card_id}/sections/{section_id}/guidance"),
    ("POST", "/api/v1/cards/{card_id}/sections/{section_id}/guidance"),
    ("GET", "/api/v1/cards/{card_id}/proposals"),
    ("POST", "/api/v1/proposals/{proposal_id}/accept"),
    ("POST", "/api/v1/proposals/{proposal_id}/discussion"),
    ("POST", "/api/v1/proposals/{proposal_id}/reject"),
    ("POST", "/api/v1/cards/{card_id}/notes"),
    ("GET", "/api/v1/cards/{card_id}/notes"),
    ("GET", "/api/v1/notes"),
    ("PATCH", "/api/v1/notes/{note_id}"),
    ("DELETE", "/api/v1/notes/{note_id}"),
}

EXPECTED_STATUS = {
    ("POST", "/api/v1/learning-spaces/{space_id}/cards"): 201,
    ("POST", "/api/v1/cards/{card_id}/sections/{section_id}/guidance"): 201,
    ("POST", "/api/v1/proposals/{proposal_id}/accept"): 201,
    ("POST", "/api/v1/proposals/{proposal_id}/discussion"): 201,
    ("POST", "/api/v1/cards/{card_id}/notes"): 201,
}


def flattened_routes(routes=None, prefix=""):
    routes = main.app.routes if routes is None else routes
    flattened = []
    for route in routes:
        nested = getattr(route, "routes", None)
        if nested is None and hasattr(route, "original_router"):
            context = route.include_context
            nested = context.included_router.routes
            route_prefix = prefix + context.prefix
            flattened.extend(flattened_routes(nested, route_prefix))
            continue
        if nested is not None:
            flattened.extend(flattened_routes(nested, prefix + getattr(route, "prefix", "")))
        elif hasattr(route, "path"):
            route._contract_path = prefix + route.path
            flattened.append(route)
    return flattened


def matching_routes(pair):
    method, path = pair
    return [
        route
        for route in flattened_routes()
        if route._contract_path == path and method in getattr(route, "methods", set())
    ]


class KnowledgeCardApiContractTests(unittest.TestCase):
    def test_all_knowledge_card_routes_are_registered_once(self):
        for pair in EXPECTED_ROUTES:
            self.assertEqual(len(matching_routes(pair)), 1, pair)

    def test_route_status_codes_preserve_existing_contract(self):
        for pair in EXPECTED_ROUTES:
            route = matching_routes(pair)[0]
            self.assertEqual(route.status_code, EXPECTED_STATUS.get(pair), pair)

    def test_knowledge_card_routes_require_authenticated_user(self):
        for route in flattened_routes():
            route_pairs_for_route = {
                (method, route._contract_path) for method in getattr(route, "methods", set())
            }
            if not route_pairs_for_route & EXPECTED_ROUTES:
                continue
            dependency_names = {
                getattr(dep.call, "__name__", "")
                for dep in route.dependant.dependencies
            }
            self.assertIn("require_current_user", dependency_names, route._contract_path)

    def test_legacy_api_no_longer_defines_knowledge_card_handlers(self):
        removed = {
            "list_cards", "create_card", "get_card", "delete_card",
            "list_teacher_guidance", "create_section_guidance",
            "list_card_proposals", "accept_proposal", "start_proposal_discussion",
            "reject_proposal", "create_note", "list_notes", "list_all_notes",
            "update_note", "delete_note",
        }
        for name in removed:
            self.assertFalse(hasattr(api, name), name)

    def test_extracted_router_is_independent_of_legacy_api(self):
        import backend.knowledge_card_api as knowledge_card_api

        source = inspect.getsource(knowledge_card_api)
        self.assertNotIn("from .api import", source)
        self.assertNotIn("from backend.api import", source)


if __name__ == "__main__":
    unittest.main()
