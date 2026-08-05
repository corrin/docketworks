"""The one LLM call boundary (ADR 0041): provider resolution and the completion.

This is the ONLY file in the repo allowed to mock below ``chat_completion`` —
everywhere else that function IS the boundary and litellm never runs. Here the
subject is the boundary itself, so ``litellm.completion`` is faked and what the
gateway hands it is asserted.

The tests pin provider-row compatibility across data restores and require an
unknown provider type to fail at configuration, before LiteLLM receives an
ambiguous unprefixed model name.
"""

from dataclasses import dataclass
from unittest.mock import patch

import pytest

from apps.ai.enums import AIProviderTypes
from apps.ai.models import AIProvider
from apps.ai.services.llm_client import (
    COMPLETION_TIMEOUT_SECONDS,
    LITELLM_PROVIDER_PREFIXES,
    PARSING_PROVIDER_TYPE,
    LLMConfigurationError,
    LLMEmptyResponseError,
    chat_completion,
    resolve_target,
)

pytestmark = [pytest.mark.django_db]

LITELLM_COMPLETION = "litellm.completion"


@dataclass(frozen=True)
class FakeMessage:
    content: str | None


@dataclass(frozen=True)
class FakeChoice:
    message: FakeMessage


@dataclass(frozen=True)
class FakeResponse:
    choices: list[FakeChoice]


def reply(content: str | None) -> FakeResponse:
    """A litellm completion response carrying this content."""
    return FakeResponse(choices=[FakeChoice(message=FakeMessage(content=content))])


def make_provider(
    *,
    name: str = "Gemini Flash",
    provider_type: str = AIProviderTypes.GOOGLE,
    api_key: str | None = "test-key",
    model_name: str | None = "gemini-flash-latest",
    default: bool = False,
) -> AIProvider:
    """A configured provider row."""
    return AIProvider.objects.create(
        name=name,
        provider_type=provider_type,
        api_key=api_key,
        model_name=model_name,
        default=default,
    )


class TestResolveTarget:
    def test_a_named_provider_type_is_selected_and_prefixed_for_litellm(self) -> None:
        make_provider()

        target = resolve_target(AIProviderTypes.GOOGLE)

        assert target.model == "gemini/gemini-flash-latest"
        assert target.api_key == "test-key"
        assert target.provider_name == "Gemini Flash"

    def test_with_no_type_asked_for_the_default_provider_wins(self) -> None:
        make_provider(name="Mistral", provider_type=AIProviderTypes.MISTRAL, model_name="large")
        make_provider(name="Gemini Flash", default=True)

        assert resolve_target().provider_name == "Gemini Flash"

    def test_two_default_rows_are_a_configuration_fault_not_a_coin_toss(self) -> None:
        """Two default=True rows and .first() picks by table order — the same
        silent arbitrariness as the no-default fallback, one door over. No DB
        constraint enforces the invariant (v2.0 migrates by pg_dump/restore,
        so the schema cannot grow one), so the gateway checks it."""
        make_provider(name="Gemini Flash", default=True)
        make_provider(
            name="Mistral",
            provider_type=AIProviderTypes.MISTRAL,
            model_name="large",
            default=True,
        )

        with pytest.raises(LLMConfigurationError, match="exactly one"):
            resolve_target()

    def test_with_no_default_configured_the_config_is_the_fault(self) -> None:
        """ADR 0015: silently picking an ARBITRARY provider — vendor, model and
        API key decided by table order — is a fallback that masks a config
        problem. The fix is one click on the admin, so demand it."""
        make_provider(name="Mistral", provider_type=AIProviderTypes.MISTRAL, model_name="large")

        with pytest.raises(LLMConfigurationError, match="none is marked default"):
            resolve_target()

    @pytest.mark.parametrize(
        ("provider_type", "model_name", "expected"),
        [
            (AIProviderTypes.GOOGLE, "gemini-flash-latest", "gemini/gemini-flash-latest"),
            (AIProviderTypes.MISTRAL, "mistral-large-latest", "mistral/mistral-large-latest"),
            (AIProviderTypes.OPENAI, "gpt-4o", "openai/gpt-4o"),
            # Claude carries no prefix in litellm.
            (AIProviderTypes.ANTHROPIC, "claude-sonnet-4-5", "claude-sonnet-4-5"),
        ],
    )
    def test_every_supported_vendor_is_a_config_row_not_a_client(
        self, provider_type: str, model_name: str, expected: str
    ) -> None:
        make_provider(name=provider_type, provider_type=provider_type, model_name=model_name)

        assert resolve_target(provider_type).model == expected

    def test_the_prefix_table_covers_every_provider_type_the_enum_offers(self) -> None:
        """A new vendor is one enum member plus one row here — never a new client."""
        assert set(LITELLM_PROVIDER_PREFIXES) == {
            value for value, _label in AIProviderTypes.choices
        }

    def test_an_empty_database_names_the_missing_configuration(self) -> None:
        with pytest.raises(LLMConfigurationError, match="No AI provider configured"):
            resolve_target()

    def test_asking_for_a_type_nobody_configured_names_that_type(self) -> None:
        make_provider(name="Mistral", provider_type=AIProviderTypes.MISTRAL, model_name="large")

        with pytest.raises(LLMConfigurationError, match="No AI provider of type Gemini"):
            resolve_target(AIProviderTypes.GOOGLE)

    def test_a_provider_with_no_api_key_names_the_provider(self) -> None:
        make_provider(api_key=None)

        with pytest.raises(LLMConfigurationError, match="Gemini Flash AI provider is missing an"):
            resolve_target(AIProviderTypes.GOOGLE)

    def test_a_provider_with_no_model_name_names_the_provider(self) -> None:
        make_provider(model_name=None)

        with pytest.raises(LLMConfigurationError, match="missing a model name"):
            resolve_target(AIProviderTypes.GOOGLE)

    def test_a_provider_type_litellm_has_no_prefix_for_lists_the_known_ones(self) -> None:
        """Provider-prefixed model names make configuration failures legible."""
        AIProvider.objects.create(
            name="Homegrown", provider_type="Homegrown", api_key="k", model_name="m"
        )

        with pytest.raises(LLMConfigurationError, match="unsupported provider_type 'Homegrown'"):
            resolve_target("Homegrown")


class TestChatCompletion:
    def test_the_prompt_is_sent_as_one_user_message_with_the_configured_key(self) -> None:
        make_provider()

        with patch(LITELLM_COMPLETION, return_value=reply("parsed")) as completion:
            assert chat_completion("Parse this", provider_type=AIProviderTypes.GOOGLE) == "parsed"

        _args, kwargs = completion.call_args
        assert kwargs["model"] == "gemini/gemini-flash-latest"
        assert kwargs["api_key"] == "test-key"
        assert kwargs["messages"] == [{"role": "user", "content": "Parse this"}]

    def test_every_completion_is_bounded_by_an_explicit_timeout(self) -> None:
        """litellm's own default is 6000s — 100 minutes — which is a hang, not a timeout.

        It applies per call and product parsing issues one call per product, so
        a provider that stops responding mid-catalogue would wedge a Celery
        worker until someone noticed.
        """
        make_provider(default=True)

        with patch(LITELLM_COMPLETION, return_value=reply("parsed")) as completion:
            chat_completion("Parse this")

        _args, kwargs = completion.call_args
        assert kwargs["timeout"] == COMPLETION_TIMEOUT_SECONDS
        assert COMPLETION_TIMEOUT_SECONDS < 600, (
            "a timeout this long is indistinguishable from none"
        )

    def test_a_completion_with_no_content_is_an_error_not_an_empty_string(self) -> None:
        """ADR 0038: "" would flow on and look like a model that answered nothing.

        And it is a MODEL outcome, not a configuration fault: callers let
        configuration errors propagate (the shop must fix its provider row),
        but treat an unusable reply as a routine per-item failure. Raising
        LLMConfigurationError here made one empty completion abort an entire
        end-of-run fill.
        """
        make_provider(default=True)

        with (
            patch(LITELLM_COMPLETION, return_value=reply(None)),
            pytest.raises(LLMEmptyResponseError, match="returned a completion with no content"),
        ):
            chat_completion("Parse this")

    def test_configuration_is_resolved_before_any_vendor_call_is_made(self) -> None:
        with patch(LITELLM_COMPLETION) as completion, pytest.raises(LLMConfigurationError):
            chat_completion("Parse this")

        completion.assert_not_called()

    def test_the_parser_pins_gemini_the_way_v1_did(self) -> None:
        """Cheap and fast, and enough to turn a description into inventory fields."""
        assert PARSING_PROVIDER_TYPE == AIProviderTypes.GOOGLE
