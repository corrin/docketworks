from django.test import SimpleTestCase

from apps.quoting.services.ai_price_extraction import PriceExtractionFactory
from apps.quoting.services.providers.gemini_provider import (
    GEMINI_FLASH_MODEL,
    GeminiPriceExtractionProvider,
)
from apps.workflow.enums import AIProviderTypes


class GeminiModelSelectionTests(SimpleTestCase):
    def test_provider_defaults_to_rolling_flash_alias(self) -> None:
        provider = GeminiPriceExtractionProvider("test-api-key")

        self.assertEqual(provider.model_name, GEMINI_FLASH_MODEL)

    def test_factory_uses_rolling_flash_alias_when_model_is_not_configured(
        self,
    ) -> None:
        provider = PriceExtractionFactory.create_provider(
            AIProviderTypes.GOOGLE,
            "test-api-key",
            "",
        )

        self.assertIsInstance(provider, GeminiPriceExtractionProvider)
        self.assertEqual(provider.model_name, GEMINI_FLASH_MODEL)

    def test_factory_preserves_an_explicit_gemini_model(self) -> None:
        provider = PriceExtractionFactory.create_provider(
            AIProviderTypes.GOOGLE,
            "test-api-key",
            "gemini-pro-latest",
        )

        self.assertEqual(provider.model_name, "gemini-pro-latest")
