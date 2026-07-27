"""
Centralized LLM Service using LiteLLM.

Provides a unified interface for all LLM calls across the application,
supporting Claude, Gemini, Mistral, and other providers through LiteLLM.

Usage:
    from apps.workflow.services.llm_service import LLMService

    llm = LLMService()
    response = llm.completion(
        messages=[{"role": "user", "content": "Hello"}],
        system_prompt="You are a helpful assistant",
    )
"""

import base64
import json
import logging
import mimetypes
from pathlib import Path
from typing import Any

import litellm
from litellm import completion

from apps.workflow.enums import AIProviderTypes
from apps.workflow.models import AIProvider
from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger(__name__)

# Disable LiteLLM's verbose logging
litellm.set_verbose = False
litellm.suppress_debug_info = True

# Suppress LiteLLM debug logger
logging.getLogger("LiteLLM").setLevel(logging.WARNING)
logging.getLogger("litellm").setLevel(logging.WARNING)

# Map AIProviderTypes to LiteLLM model prefixes
LITELLM_PROVIDER_PREFIXES = {
    AIProviderTypes.GOOGLE: "gemini/",
    AIProviderTypes.ANTHROPIC: "",  # Claude models don't need prefix
    AIProviderTypes.MISTRAL: "mistral/",
    AIProviderTypes.OPENAI: "openai/",
}


class LLMService:
    """
    Centralized service for LLM interactions using LiteLLM.

    Supports multiple providers (Claude, Gemini, Mistral) through a unified API.
    Automatically loads configuration from the AIProvider model.
    """

    def __init__(self, provider_type: str | None = None):
        """
        Initialize the LLM service.

        Args:
            provider_type: Optional specific provider to use.
                          If None, uses the default AIProvider.
        """
        self._configure(provider_type)

    def _configure(self, provider_type: str | None = None):
        """Configure LiteLLM with the specified or default provider."""
        if provider_type:
            ai_provider = AIProvider.objects.filter(provider_type=provider_type).first()
        else:
            ai_provider = AIProvider.get_default()
            if not ai_provider:
                ai_provider = AIProvider.objects.first()

        if not ai_provider:
            raise ValueError("No AI provider configured in the database")

        if not ai_provider.api_key:
            raise ValueError(f"{ai_provider.name} AI provider is missing an API key")

        if not ai_provider.model_name:
            raise ValueError(f"{ai_provider.name} AI provider is missing a model name")

        self.provider_type = ai_provider.provider_type
        self.api_key = ai_provider.api_key
        self.provider_name = ai_provider.name

        # Build the full model name for LiteLLM
        prefix = LITELLM_PROVIDER_PREFIXES.get(ai_provider.provider_type, "")
        self.model_name = f"{prefix}{ai_provider.model_name}"

        logger.debug(f"LLMService configured with model: {self.model_name}")

    def completion(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        stream: bool = False,
        **kwargs,
    ) -> Any:
        """
        Make a completion request to the LLM.

        Args:
            messages: List of message dicts with 'role' and 'content'
            system_prompt: Optional system prompt (prepended to messages)
            tools: Optional list of tool/function definitions
            tool_choice: Optional tool choice specification
            temperature: Optional temperature (0.0-1.0)
            max_tokens: Optional max tokens for response
            response_format: Optional response format (e.g., {"type": "json_object"})
            stream: Whether to stream the response
            **kwargs: Additional parameters passed to LiteLLM

        Returns:
            LiteLLM completion response object
        """
        try:
            # Build messages list
            final_messages = []

            if system_prompt:
                final_messages.append(
                    {
                        "role": "system",
                        "content": system_prompt,
                    }
                )

            final_messages.extend(messages)

            # Build completion kwargs
            completion_kwargs = {
                "model": self.model_name,
                "messages": final_messages,
                "api_key": self.api_key,
                "stream": stream,
            }

            if tools:
                completion_kwargs["tools"] = tools
            if tool_choice:
                completion_kwargs["tool_choice"] = tool_choice
            if temperature is not None:
                completion_kwargs["temperature"] = temperature
            if max_tokens is not None:
                completion_kwargs["max_tokens"] = max_tokens
            if response_format:
                completion_kwargs["response_format"] = response_format

            # Add any extra kwargs
            completion_kwargs.update(kwargs)

            logger.debug(f"LLM completion request to {self.model_name}")
            response = completion(**completion_kwargs)
            logger.debug("LLM completion successful")

            return response

        except Exception as exc:
            logger.exception(f"LLM completion failed: {exc}")
            persist_app_error(exc)
            raise

    def completion_with_json(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs,
    ) -> dict:
        """
        Make a completion request expecting JSON response.

        Automatically parses the response and handles markdown code blocks.

        Args:
            messages: List of message dicts
            system_prompt: Optional system prompt
            temperature: Optional temperature
            max_tokens: Optional max tokens
            **kwargs: Additional parameters

        Returns:
            Parsed JSON dict from response
        """
        response = self.completion(
            messages=messages,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            **kwargs,
        )

        text = response.choices[0].message.content.strip()
        return self._parse_json_response(text)

    def _parse_json_response(self, text: str) -> dict:
        """Parse JSON from LLM response, handling markdown code blocks."""
        # Handle markdown code blocks
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.debug(f"Raw response: {text[:500]}")
            raise ValueError(f"LLM returned invalid JSON: {e}") from e

    def get_text_response(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        **kwargs,
    ) -> str:
        """
        Make a completion request and return just the text content.

        Args:
            messages: List of message dicts
            system_prompt: Optional system prompt
            **kwargs: Additional parameters

        Returns:
            Text content from response
        """
        response = self.completion(
            messages=messages,
            system_prompt=system_prompt,
            **kwargs,
        )
        return response.choices[0].message.content

    @staticmethod
    def create_image_message(
        image_path: str | Path,
        prompt: str,
        detail: str = "auto",
    ) -> dict:
        """
        Create a message with an image for vision models.

        Args:
            image_path: Path to the image file
            prompt: Text prompt to accompany the image
            detail: Image detail level ("auto", "low", "high")

        Returns:
            Message dict with image content
        """
        image_path = Path(image_path)

        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        # Detect MIME type
        mime_type, _ = mimetypes.guess_type(str(image_path))
        if not mime_type:
            mime_type = "image/png"  # Default fallback

        # Read and encode image
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        return {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{image_data}",
                        "detail": detail,
                    },
                },
                {
                    "type": "text",
                    "text": prompt,
                },
            ],
        }

    @staticmethod
    def create_pdf_message(
        pdf_path: str | Path,
        prompt: str,
    ) -> dict:
        """
        Create a message with a PDF for models that support it.

        Args:
            pdf_path: Path to the PDF file
            prompt: Text prompt to accompany the PDF

        Returns:
            Message dict with PDF content
        """
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        # Read and encode PDF
        with open(pdf_path, "rb") as f:
            pdf_data = base64.b64encode(f.read()).decode("utf-8")

        return {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:application/pdf;base64,{pdf_data}",
                    },
                },
                {
                    "type": "text",
                    "text": prompt,
                },
            ],
        }

    def supports_vision(self) -> bool:
        """Check if the current model supports vision/image input."""
        vision_models = [
            "gemini",
            "claude-3",
            "gpt-4-vision",
            "gpt-4o",
            "gpt-4-turbo",
            "pixtral",
        ]
        return any(vm in self.model_name.lower() for vm in vision_models)

    def supports_tools(self) -> bool:
        """Check if the current model supports function calling/tools."""
        # Most modern models support tools
        tool_models = [
            "gemini",
            "claude",
            "gpt-4",
            "gpt-3.5-turbo",
            "mistral",
        ]
        return any(tm in self.model_name.lower() for tm in tool_models)


# Convenience function for quick completions
def quick_completion(
    prompt: str,
    system_prompt: str | None = None,
    provider_type: str | None = None,
    **kwargs,
) -> str:
    """
    Quick helper for simple text completions.

    Args:
        prompt: User prompt
        system_prompt: Optional system prompt
        provider_type: Optional specific provider
        **kwargs: Additional parameters

    Returns:
        Text response from LLM
    """
    llm = LLMService(provider_type=provider_type)
    return llm.get_text_response(
        messages=[{"role": "user", "content": prompt}],
        system_prompt=system_prompt,
        **kwargs,
    )


def quick_json_completion(
    prompt: str,
    system_prompt: str | None = None,
    provider_type: str | None = None,
    **kwargs,
) -> dict:
    """
    Quick helper for JSON completions.

    Args:
        prompt: User prompt (should request JSON output)
        system_prompt: Optional system prompt
        provider_type: Optional specific provider
        **kwargs: Additional parameters

    Returns:
        Parsed JSON dict from LLM
    """
    llm = LLMService(provider_type=provider_type)
    return llm.completion_with_json(
        messages=[{"role": "user", "content": prompt}],
        system_prompt=system_prompt,
        **kwargs,
    )
