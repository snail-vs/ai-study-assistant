import unittest
from pathlib import Path
from unittest.mock import patch

from backend import api
from backend.main import app
from backend.provider_api import router as provider_router
from backend.security.auth import require_current_user
from backend.services import provider_settings
from backend.services import chatgpt_oauth


class ProviderApiContractTests(unittest.TestCase):
    def test_openapi_exposes_exact_provider_route_contract(self):
        expected = {
            ("PUT", "/api/v1/settings/model"),
            ("GET", "/api/v1/settings/model-routes"),
            ("PUT", "/api/v1/settings/model-routes"),
            ("GET", "/api/v1/settings/providers"),
            ("POST", "/api/v1/settings/providers/chatgpt/oauth/complete"),
            ("POST", "/api/v1/settings/providers/chatgpt/oauth/login"),
            ("POST", "/api/v1/settings/providers/chatgpt/oauth/logout"),
            ("POST", "/api/v1/settings/providers/chatgpt/oauth/status"),
            ("DELETE", "/api/v1/settings/providers/{provider_name}"),
            ("PUT", "/api/v1/settings/providers/{provider_name}"),
            ("POST", "/api/v1/settings/providers/{provider_name}/models"),
        }
        actual = {
            (method.upper(), path)
            for path, operation in app.openapi()["paths"].items()
            for method in operation
            if method.lower() in {"get", "post", "put", "delete", "patch"}
            and path.startswith("/api/v1/settings/")
        }
        self.assertEqual(actual, expected)

        route_keys = [key for key in actual]
        self.assertEqual(len(route_keys), len(set(route_keys)))

    def test_extracted_router_routes_require_current_user(self):
        self.assertTrue(provider_router.dependencies)
        self.assertTrue(
            any(
                getattr(dependency, "dependency", None) is require_current_user
                for dependency in provider_router.dependencies
            )
        )
        for route in provider_router.routes:
            self.assertTrue(
                any(
                    dependency.dependency is require_current_user
                    for dependency in route.dependencies
                ),
                route.path,
            )

    def test_api_restore_active_provider_keeps_service_identity_and_patch_seam(self):
        self.assertIs(api.restore_active_provider, provider_settings.restore_active_provider)
        replacement = object()
        with patch.object(api, "restore_active_provider", return_value=replacement):
            self.assertIs(api.restore_active_provider(), replacement)

    def test_oauth_workflow_service_has_no_router_or_api_dependency(self):
        source = Path(chatgpt_oauth.__file__).read_text()
        self.assertNotIn("from ..api", source)
        self.assertNotIn("from ..provider_api", source)
        self.assertNotIn("import router", source)

    def test_oauth_routes_delegate_to_service_workflow(self):
        source = Path(__file__).parents[1].joinpath("provider_api.py").read_text()
        for symbol in ("start_login", "login_status", "complete_login", "logout"):
            self.assertIn(symbol, source)


if __name__ == "__main__":
    unittest.main()
