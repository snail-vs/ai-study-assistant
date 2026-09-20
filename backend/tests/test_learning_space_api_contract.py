import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from backend import api
from backend.learning_space_api import router as learning_space_router
from backend.main import app
from backend.security.auth import require_current_user
from backend.services import course_generation


class LearningSpaceApiContractTests(unittest.TestCase):
    def test_openapi_exposes_exact_learning_space_generation_routes(self):
        expected = {
            ("POST", "/api/v1/learning-spaces"),
            ("GET", "/api/v1/learning-spaces"),
            ("GET", "/api/v1/learning-spaces/{space_id}"),
            ("DELETE", "/api/v1/learning-spaces/{space_id}"),
            ("GET", "/api/v1/learning-spaces/{space_id}/generation"),
            ("PUT", "/api/v1/learning-spaces/{space_id}/generation"),
            ("GET", "/api/v1/learning-spaces/{space_id}/runtime"),
            ("PUT", "/api/v1/learning-spaces/{space_id}/runtime"),
        }
        actual = {
            (method.upper(), path)
            for path, operation in app.openapi()["paths"].items()
            for method in operation
            if method.lower() in {"get", "post", "put", "delete", "patch"}
            and (
                path == "/api/v1/learning-spaces"
                or path == "/api/v1/learning-spaces/{space_id}"
                or path == "/api/v1/learning-spaces/{space_id}/generation"
                or path == "/api/v1/learning-spaces/{space_id}/runtime"
            )
        }
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), len(expected))

    def test_learning_space_router_requires_current_user_for_every_route(self):
        self.assertTrue(learning_space_router.dependencies)
        self.assertTrue(
            any(
                getattr(dependency, "dependency", None) is require_current_user
                for dependency in learning_space_router.dependencies
            )
        )
        for route in learning_space_router.routes:
            self.assertTrue(
                any(
                    dependency.dependency is require_current_user
                    for dependency in route.dependencies
                ),
                route.path,
            )

    def test_legacy_api_router_no_longer_owns_learning_space_generation_routes(self):
        legacy_paths = {
            route.path
            for route in api.router.routes
            if route.path in {
                "/learning-spaces",
                "/learning-spaces/{space_id}",
                "/learning-spaces/{space_id}/generation",
                "/learning-spaces/{space_id}/runtime",
            }
        }
        self.assertEqual(legacy_paths, set())

    def test_main_startup_uses_service_resume_function_seam(self):
        import backend.main as main_module

        self.assertIs(
            main_module.resume_pending_course_generations,
            course_generation.resume_pending_course_generations,
        )

        async def exercise_startup():
            with patch.object(
                main_module,
                "resume_pending_course_generations",
                new_callable=AsyncMock,
            ) as resume:
                await main_module.resume_course_generations()
                resume.assert_awaited_once_with()

        asyncio.run(exercise_startup())


if __name__ == "__main__":
    unittest.main()
