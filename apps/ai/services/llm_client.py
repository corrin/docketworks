"""The single LLM call boundary for the application.

The currently required operation is a plain-text completion. Vision helpers,
tool-calling probes, and parallel convenience clients are deliberately absent
until a real caller needs them (ADR 0017).

Layer contract: ``apps.ai`` sits in the bottom (infrastructure) layer beside
``apps.core``, so every domain app imports this gateway directly. A registry
seam would encourage parallel clients for the same capability.

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

# Provider prefixes are keyed by AIProviderTypes so a new provider is a
# type-checked addition rather than a loose string. Claude carries no prefix
# in LiteLLM; adding a vendor means one row here plus one enum member — never a
# new client (ADR 0041).
LITELLM_PROVIDER_PREFIXES: dict[str, str] = {
    AIProviderTypes.GOOGLE: "gemini/",
    AIProviderTypes.ANTHROPIC: "",
    AIProviderTypes.MISTRAL: "mistral/",
    AIProviderTypes.OPENAI: "openai/",
}

# Product parsing uses Google/Gemini Flash because it is cheap, fast, and
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

    A named type lets callers tell "the shop has not configured AI yet" apart from "the model
    returned nonsense" without matching on message text (ADR 0038).
    """


class LLMEmptyResponseError(RuntimeError):
    """Raised when the model returned a completion with no content.

    Deliberately NOT ``LLMConfigurationError``: callers let configuration
    errors propagate (someone must fix the provider row) but treat an unusable
    reply as a routine per-item outcome — conflating the two let one empty
    completion abort an entire end-of-run fill.
    """


@dataclass(frozen=True, slots=True)
class LLMTarget:
    """A resolved, fully validated completion target."""

    model: str
    api_key: str
    provider_name: str


def resolve_target(provider_type: str | None = None) -> LLMTarget:
    """Resolve the provider to call, or raise naming exactly what is missing.

    A specific ``provider_type`` selects that provider; otherwise the default
    one is selected. If rows exist but none is marked default, this raises rather than
    with rows configured but none marked default, this raises rather than
    letting table order pick the vendor (ADR 0015).
    """
    catalogue = AIProvider.objects
    if provider_type:
        provider = catalogue.filter(provider_type=provider_type).first()
        if provider is None:
            raise LLMConfigurationError(
                f"No AI provider of type {provider_type} is configured in the database"
            )
    else:
        # No arbitrary choice in either direction (ADR 0015): zero defaults or
        # several, table order would silently pick the vendor, model and API
        # key. Checked here rather than by a DB constraint because deployment migrates by
        # pg_dump/restore, so the schema cannot grow one.
        default_rows = list(catalogue.filter(default=True)[:2])
        if len(default_rows) > 1:
            raise LLMConfigurationError(
                "More than one AI provider is marked default; "
                "set default=True on exactly one AIProvider row"
            )
        provider = default_rows[0] if default_rows else None
        if provider is None:
            if not catalogue.exists():
                raise LLMConfigurationError("No AI provider configured in the database")
            raise LLMConfigurationError(
                "AI providers are configured but none is marked default; "
                "set default=True on exactly one AIProvider row"
            )

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
        raise LLMEmptyResponseError(f"{target.model} returned a completion with no content")
    return content
