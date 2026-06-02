import abc
import logging
from typing import Any, Dict, Optional, Tuple

from apps.workflow.enums import AIProviderTypes

from .providers.gemini_provider import GeminiPriceExtractionProvider

# from .providers.claude_provider import ClaudePriceExtractionProvider
from .providers.mistral_provider import MistralPriceExtractionProvider

logger = logging.getLogger(__name__)


class PriceExtractionProvider(abc.ABC):
    """Abstract base class for AI price extraction providers."""

    provider_name: str

    @abc.abstractmethod
    def extract_price_data(
        self, file_path: str, content_type: Optional[str] = None
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Extract price data from a supplier price list file.

        Args:
            file_path: Path to the price list file
            content_type: MIME type of the file

        Returns:
            Tuple containing extracted data dict and error message if any
        """


class PriceExtractionFactory:
    """Factory for creating AI price extraction providers."""

    @staticmethod
    def create_provider(
        provider_type: str, api_key: str, model_name: str = None
    ) -> PriceExtractionProvider:
        """Create a provider instance based on type."""
        if provider_type == AIProviderTypes.MISTRAL:
            return MistralPriceExtractionProvider(api_key)
        elif provider_type == AIProviderTypes.GOOGLE:
            return GeminiPriceExtractionProvider(
                api_key, model_name or "gemini-2.0-flash-exp"
            )
        #        elif provider_type == AIProviderTypes.ANTHROPIC:
        #            return ClaudePriceExtractionProvider(api_key)
        else:
            raise ValueError(f"Unsupported provider type: {provider_type}")


def get_prioritized_active_providers():
    """
    Get all AI providers with API keys sorted by priority.
    Priority order: Mistral > Claude > Gemini
    """
    from apps.workflow.models import AIProvider

    active_providers = AIProvider.objects.filter(api_key__isnull=False).exclude(
        api_key=""
    )

    # Define priority order (lower number = higher priority)
    priority_map = {
        AIProviderTypes.MISTRAL: 1,
        #        AIProviderTypes.ANTHROPIC: 3,  # Claude
        AIProviderTypes.GOOGLE: 2,  # Gemini
    }

    # Sort by priority
    sorted_providers = sorted(
        active_providers, key=lambda p: priority_map.get(p.provider_type, 999)
    )

    return sorted_providers


def extract_price_data(
    file_path: str, content_type: Optional[str] = None
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Price extraction function that uses the highest priority active AI provider.

    Args:
        file_path: Path to the price list file
        content_type: MIME type of the file

    Returns:
        Tuple containing extracted data dict and error message if any
    """
    logger.info(
        f"Starting price extraction for file: {file_path}, content_type: {content_type}"
    )

    # 1. Get all active providers
    logger.info("Getting prioritized active providers...")
    prioritized_providers = get_prioritized_active_providers()
    logger.info(f"Found {len(prioritized_providers)} active providers")

    if not prioritized_providers:
        error_msg = "No active AI providers configured with API keys. Please configure one in company settings."
        logger.error(error_msg)
        return (None, error_msg)

    # 2. Use the top priority provider (Mistral first)
    ai_provider = prioritized_providers[0]
    logger.info(
        f"Selected AI provider: {ai_provider.provider_type}, model: {ai_provider.model_name}"
    )
    logger.info(f"API key present: {bool(ai_provider.api_key)}")

    # 3. Create provider instance and call - fail early, don't eat errors
    try:
        logger.info("Creating provider instance...")
        provider = PriceExtractionFactory.create_provider(
            ai_provider.provider_type, ai_provider.api_key, ai_provider.model_name
        )
        logger.info(f"Provider created successfully: {provider.provider_name}")

        logger.info(f"Starting extraction with {provider.provider_name}")
        result = provider.extract_price_data(file_path, content_type)
        logger.info(f"Extraction completed with {provider.provider_name}")
        return result
    except Exception as e:
        logger.exception(
            f"Error creating or using provider {ai_provider.provider_type}: {e}"
        )
        return (None, f"Provider error: {str(e)}")
