"""The single LLM call boundary in v2, ported from v1 ``apps/workflow/services/llm_service.py``.

v1's ``LLMService`` was a 400-line class wrapping LiteLLM with vision helpers,
tool-calling probes, JSON parsing and four module-level convenience functions.
Exactly one of those paths has a caller in this slice — a plain text completion
issued by the product parser — so v2 ports that one path and nothing else (ADR
0017). The provider-prefix table and the AIProvider-driven configuration are
v1's, unchanged, so a migrated v1 database keeps working.

Layer contract: ``apps.ai`` sits in the bottom (infrastructure) layer beside
``apps.core``, so every domain app imports this gateway directly — no registry
seam, because making the correct call awkward is how v1 grew four clients.

AI runs across the app — price extraction, product/stock parsing, the quoting
chatbot, MCP tools, supplier enrichment, quote-to-PO — and every one of those
calls arrives here.
"""

import logging
from dataclasses import dataclass

import litellm

from apps.ai.enums import AIProviderTypes
from apps.ai.models import AIProvider

logger = logging.getLogger(__name__)

# v1 LITELLM_PROVIDER_PREFIXES, keyed by AIProviderTypes so a new provider is
# a type-checked addition rather than a loose string. Claude carries no prefix
# in LiteLLM; adding a vendor means one row here plus one enum member — never a
# new client (ADR 0041).
LITELLM_PROVIDER_PREFIXES: dict[str, str] = {
    AIProviderTypes.GOOGLE: "gemini/",
    AIProviderTypes.ANTHROPIC: "",
    AIProviderTypes.MISTRAL: "mistral/",
    AIProviderTypes.OPENAI: "openai/",
}

# v1 ProductParser pinned Google/Gemini Flash for parsing: cheap and fast, and
# sufficient for turning a product description into inventory fields.
PARSING_PROVIDER_TYPE: str = AIProviderTypes.GOOGLE

#: Wall-clock ceiling on one completion. LiteLLM's own default is
#: ``DEFAULT_REQUEST_TIMEOUT_SECONDS = 6000`` — 100 minutes — which is not a
#: timeout so much as a hang. It applies PER CALL, and product parsing issues
#: one call per product, so a provider that stops responding mid-catalogue would
#: wedge a Celery worker for as long as it took anyone to notice. Two minutes is
#: far above the ~2-5s these completions actually take while still bounding the
#: damage, and a timeout surfaces as a real error rather than silence (ADR 0038).
COMPLETION_TIMEOUT_SECONDS: float = 120.0


class LLMConfigurationError(RuntimeError):
    """Raised when no usable AI provider is configured, or its type is unknown.

    v1 raised a bare ``ValueError`` from ``LLMService._configure``; a named type
    lets callers tell "the shop has not configured AI yet" apart from "the model
    returned nonsense" without matching on message text (ADR 0038).
    """


@dataclass(frozen=True, slots=True)
class LLMTarget:
    """A resolved, fully validated completion target."""

    model: str
    api_key: str
    provider_name: str


def resolve_target(provider_type: str | None = None) -> LLMTarget:
    """Resolve the provider to call, or raise naming exactly what is missing.

    v1 ``LLMService._configure``: a specific ``provider_type`` selects that
    provider; otherwise the default one, otherwise any. Every validation is
    v1's, plus the unknown-provider-type check v1 lacked.
    """
    catalogue = AIProvider.objects
    if provider_type:
        provider = catalogue.filter(provider_type=provider_type).first()
        if provider is None:
            raise LLMConfigurationError(
                f"No AI provider of type {provider_type} is configured in the database"
            )
    else:
        provider = catalogue.filter(default=True).first() or catalogue.all().first()
        if provider is None:
            raise LLMConfigurationError("No AI provider configured in the database")

    api_key = provider.api_key
    if not api_key:
        raise LLMConfigurationError(f"{provider.name} AI provider is missing an API key")
    model_name = provider.model_name
    if not model_name:
        raise LLMConfigurationError(f"{provider.name} AI provider is missing a model name")
    prefix = LITELLM_PROVIDER_PREFIXES.get(provider.provider_type)
    if prefix is None:
        raise LLMConfigurationError(
            f"{provider.name} AI provider has unsupported provider_type "
            f"{provider.provider_type!r}; known types are "
            f"{sorted(LITELLM_PROVIDER_PREFIXES)}"
        )
    return LLMTarget(model=f"{prefix}{model_name}", api_key=api_key, provider_name=provider.name)


def chat_completion(prompt: str, *, provider_type: str | None = None) -> str:
    """Send one user-role prompt to the configured LLM and return its text.

    THE LLM BOUNDARY. Tests mock this function and nothing below it, so
    everything above it — prompting, JSON extraction, mapping persistence and
    back-flow — runs for real.
    """
    target = resolve_target(provider_type)

    litellm.suppress_debug_info = True
    logger.debug("LLM completion request to %s", target.model)
    response = litellm.completion(
        model=target.model,
        messages=[{"role": "user", "content": prompt}],
        api_key=target.api_key,
        timeout=COMPLETION_TIMEOUT_SECONDS,
    )
    content = response.choices[0].message.content
    if content is None:
        raise LLMConfigurationError(f"{target.model} returned a completion with no content")
    return content
