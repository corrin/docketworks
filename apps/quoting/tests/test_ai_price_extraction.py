from django.test import SimpleTestCase

from apps.quoting.services.ai_price_extraction import PriceExtractionFactory
from apps.quoting.services.providers.base import PriceExtractionProvider
from apps.quoting.services.providers.gemini_provider import (
    GEMINI_FLASH_MODEL,
    GeminiPriceExtractionProvider,
)
from apps.quoting.services.providers.mistral_provider import (
    MISTRAL_OCR_MODEL,
    MistralPriceExtractionProvider,
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


class ProviderContractTests(SimpleTestCase):
    """Every provider the factory can return honours the shared contract."""

    def test_factory_returns_a_provider_with_a_model_name(self) -> None:
        for provider_type in (AIProviderTypes.GOOGLE, AIProviderTypes.MISTRAL):
            with self.subTest(provider_type=provider_type):
                provider = PriceExtractionFactory.create_provider(
                    provider_type,
                    "test-api-key",
                    "",
                )

                self.assertIsInstance(provider, PriceExtractionProvider)
                self.assertTrue(provider.provider_name)
                self.assertTrue(provider.model_name)

    def test_mistral_defaults_to_the_rolling_ocr_alias(self) -> None:
        provider = MistralPriceExtractionProvider("test-api-key")

        self.assertEqual(provider.model_name, MISTRAL_OCR_MODEL)

    def test_factory_preserves_an_explicit_mistral_model(self) -> None:
        provider = PriceExtractionFactory.create_provider(
            AIProviderTypes.MISTRAL,
            "test-api-key",
            "mistral-ocr-2505",
        )

        self.assertEqual(provider.model_name, "mistral-ocr-2505")
