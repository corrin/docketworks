"""The single LLM call boundary for the application.

Plain-text consumers and the Agents runtime share provider resolution and
vendor accounting here (ADR 0041).

Layer contract: ``apps.ai`` sits in the bottom (infrastructure) layer beside
``apps.core``, so every domain app imports this gateway directly. A registry
seam would encourage parallel clients for the same capability.

AI runs across the app — price extraction, product/stock parsing, the quoting
chatbot, MCP tools, supplier enrichment, quote-to-PO — and every one of those
calls arrives here.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import TypeVar

import litellm
from agents import Agent, ModelSettings, RunContextWrapper, RunHooks
from agents.extensions.models.litellm_model import LitellmModel
from agents.items import ModelResponse as AgentModelResponse
from agents.items import TResponseInputItem
from asgiref.sync import sync_to_async
from litellm import ModelResponse

from apps.ai.enums import AIProviderTypes
from apps.ai.models import AIProvider
from apps.platform.observability.models import VendorCall
from apps.platform.observability.recording import VendorCallRecord, record_vendor_call

logger = logging.getLogger(__name__)
TContext = TypeVar("TContext")

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
    api_key: str = field(repr=False)
    provider_name: str


def _select_provider(provider_type: str | None) -> AIProvider:
    """Apply an explicit vendor filter, otherwise require the unique application default."""
    catalogue = AIProvider.objects
    if provider_type is not None:
        provider = (
            catalogue.filter(
                provider_type=provider_type, api_key__isnull=False, model_name__isnull=False
            )
            .order_by("-default", "pk")
            .first()
        )
        if provider is None:
            raise LLMConfigurationError(
                f"No AI provider of type {provider_type} is configured in the database"
            )
        return provider
    provider = catalogue.filter(default=True).first()
    if provider is not None:
        return provider
    if not catalogue.exists():
        raise LLMConfigurationError("No AI provider configured in the database")
    raise LLMConfigurationError(
        "AI providers are configured but none is marked default; "
        "select the application default in Admin > Integrations"
    )


def resolve_target(
    provider_type: str | None = None, *, provider: AIProvider | None = None
) -> LLMTarget:
    """Resolve the provider to call, or raise naming exactly what is missing.

    A specific ``provider_type`` selects that provider; otherwise the default
    one is selected. If rows exist but none is marked default, this raises rather than
    letting table order pick the vendor (ADR 0015).
    """
    if provider is not None and provider_type is not None:
        raise ValueError("Select a provider row or a vendor filter, not both")
    if provider is None:
        provider = _select_provider(provider_type)

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


def chat_completion(
    prompt: str,
    *,
    provider_type: str | None = None,
    provider: AIProvider | None = None,
    max_tokens: int | None = None,
) -> str:
    """Send one user-role prompt to the configured LLM and return its text.

    THE LLM BOUNDARY. Tests mock this function and nothing below it, so
    everything above it — prompting, JSON extraction, mapping persistence and
    back-flow — runs for real.
    """
    target = resolve_target(provider_type, provider=provider)

    litellm.suppress_debug_info = True
    logger.debug("LLM completion request to %s", target.model)
    started = time.perf_counter()
    response = litellm.completion(
        model=target.model,
        messages=[{"role": "user", "content": prompt}],
        api_key=target.api_key,
        timeout=COMPLETION_TIMEOUT_SECONDS,
        max_tokens=max_tokens,
    )
    _record_completion(target, response, started)
    content = response.choices[0].message.content
    if content is None:
        raise LLMEmptyResponseError(f"{target.model} returned a completion with no content")
    return content


def _record_completion(target: LLMTarget, response: ModelResponse, started: float) -> None:
    """Record what one completion consumed.

    ADR 0041 puts token accounting at this boundary, so the counts are read
    from the vendor's own response rather than estimated from the prompt: an
    estimate is our belief about their tokeniser, which is the thing worth
    checking rather than recording.

    Dollars are deliberately absent. litellm can compute a cost, but it does
    so from a local price table — that is a rollup over the meter, not the
    meter, and it belongs to analysis over these rows rather than to the row.
    """
    record_vendor_call(
        VendorCallRecord(
            vendor=VendorCall.Vendor.LLM,
            method="POST",
            url=f"/completion/{target.model}",
            duration_ms=int((time.perf_counter() - started) * 1000),
            tokens_in=response.usage.prompt_tokens,
            tokens_out=response.usage.completion_tokens,
            model_name=target.model,
        )
    )


def agent_model(target: LLMTarget) -> LitellmModel:
    """Use the SDK's LiteLLM adapter with the same database-owned credentials."""
    return LitellmModel(model=target.model, api_key=target.api_key)


def agent_model_settings() -> ModelSettings:
    """Bound a model turn and request the vendor's streaming usage report."""
    return ModelSettings(
        include_usage=True,
        max_tokens=4096,
        extra_args={"timeout": COMPLETION_TIMEOUT_SECONDS, "num_retries": 0},
    )


class AgentCallRecording(RunHooks[TContext]):
    """Record each model round trip, including rounds that request tools."""

    def __init__(self, target: LLMTarget) -> None:
        """Bind one run to its configured provider."""
        self.target = target
        self.started = 0.0

    async def on_llm_start(
        self,
        _context: RunContextWrapper[TContext],
        _agent: Agent[TContext],
        _system_prompt: str | None,
        _input_items: list[TResponseInputItem],
    ) -> None:
        """Start timing immediately before the SDK sends the request."""
        self.started = time.perf_counter()

    async def on_llm_end(
        self,
        _context: RunContextWrapper[TContext],
        _agent: Agent[TContext],
        response: AgentModelResponse,
    ) -> None:
        """Persist usage supplied by the vendor, never estimated token counts."""
        await sync_to_async(record_vendor_call)(
            VendorCallRecord(
                vendor=VendorCall.Vendor.LLM,
                method="POST",
                url=f"/completion/{self.target.model}",
                duration_ms=int((time.perf_counter() - self.started) * 1000),
                tokens_in=response.usage.input_tokens,
                tokens_out=response.usage.output_tokens,
                model_name=self.target.model,
            )
        )
