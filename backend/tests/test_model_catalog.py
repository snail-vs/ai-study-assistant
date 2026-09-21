import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from backend.ai.base import AIProviderError
from backend.ai.model_catalog import ModelCatalogSpec
from backend.ai.registry import PROVIDER_DEFINITIONS, ProviderDefinition, create_named_text_provider
from backend.services.provider_settings import discover_provider_models


class ModelCatalogTests(unittest.TestCase):
    def test_explicit_model_overrides_glm_default_and_uses_chat_completions(self):
        default = create_named_text_provider("glm", "key")
        explicit = create_named_text_provider("glm", "key", "glm-custom")

        self.assertEqual(default.model, "glm-5.2")
        self.assertEqual(explicit.model, "glm-custom")
        self.assertEqual(explicit.endpoint, "https://open.bigmodel.cn/api/paas/v4/chat/completions")

    def test_overseas_glm_uses_its_own_base_url(self):
        provider = create_named_text_provider("zai", "key", "glm-custom")

        self.assertEqual(provider.endpoint, "https://api.z.ai/api/paas/v4/chat/completions")

    def test_provider_catalog_has_priority_over_conventional_models_endpoint(self):
        definition = ProviderDefinition(
            "https://example.test/v1",
            "example-default",
            model_catalog=ModelCatalogSpec("https://catalog.example.test/models"),
        )
        with patch.dict(PROVIDER_DEFINITIONS, {"glm": definition}), patch(
            "backend.services.provider_settings.fetch_catalog",
            new=AsyncMock(return_value=["manual-would-win-if-supplied", "catalog-model"]),
        ), patch(
            "backend.services.provider_settings.create_named_text_provider"
        ) as conventional:
            result = asyncio.run(discover_provider_models("glm", "key"))

        self.assertEqual(result["source"], "provider_catalog")
        self.assertEqual(result["models"], ["manual-would-win-if-supplied", "catalog-model"])
        conventional.assert_not_called()

    def test_conventional_endpoint_is_used_without_provider_catalog(self):
        provider = type("Provider", (), {"list_models": AsyncMock(return_value=["glm-5.2"])})()
        with patch("backend.services.provider_settings.create_named_text_provider", return_value=provider):
            result = asyncio.run(discover_provider_models("glm", "key"))

        self.assertEqual(result, {
            "models": ["glm-5.2"],
            "source": "conventional",
            "warning": None,
            "keyValidated": True,
        })

    def test_unsupported_catalog_falls_back_to_manual_entry(self):
        provider = type(
            "Provider",
            (), {"list_models": AsyncMock(side_effect=AIProviderError("not found", status_code=404))},
        )()
        with patch("backend.services.provider_settings.create_named_text_provider", return_value=provider):
            result = asyncio.run(discover_provider_models("glm", "key"))

        self.assertEqual(result["source"], "manual")
        self.assertEqual(result["models"], [])
        self.assertFalse(result["keyValidated"])

    def test_authentication_failure_is_not_hidden_by_manual_fallback(self):
        provider = type(
            "Provider",
            (), {"list_models": AsyncMock(side_effect=AIProviderError("bad key", status_code=401))},
        )()
        with patch("backend.services.provider_settings.create_named_text_provider", return_value=provider):
            with self.assertRaisesRegex(AIProviderError, "bad key"):
                asyncio.run(discover_provider_models("glm", "key"))


if __name__ == "__main__":
    unittest.main()
