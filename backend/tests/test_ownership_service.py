import ast
import inspect
import unittest

from backend import activity_api, conversation_api, learning_space_api
from backend.services import ownership


class OwnershipDependencyBoundaryTests(unittest.TestCase):
    def test_domain_routers_use_ownership_service_instead_of_legacy_api(self):
        for module in (activity_api, learning_space_api, conversation_api):
            source = inspect.getsource(module)
            self.assertNotIn("from .api import", source, module.__name__)
            self.assertNotIn("from backend.api import", source, module.__name__)

    def test_ownership_service_is_independent_of_api_and_router(self):
        tree = ast.parse(inspect.getsource(ownership))
        imported_names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported_from = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }

        self.assertNotIn("backend.api", imported_names | imported_from)
        self.assertNotIn(".api", imported_names | imported_from)
        self.assertNotIn("APIRouter", {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        })


if __name__ == "__main__":
    unittest.main()
