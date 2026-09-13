"""One vendor's answer must not decide the restore gate for every vendor behind it."""

import pytest
from litellm.exceptions import AuthenticationError, RateLimitError

from apps.ai.enums import AIProviderTypes
from apps.ai.models import AIProvider
from scripts.ops.restore_checks import check_ai_providers

pytestmark = pytest.mark.django_db


def _provider(name: str) -> AIProvider:
    return AIProvider.objects.create(
        name=name,
        provider_type=AIProviderTypes.OPENAI,
        model_name="test-model",
        api_key="private-test-key",
    )


def _refusal(exception: type[AuthenticationError] | type[RateLimitError]) -> Exception:
    """Build the vendor exception litellm raises, whose constructor demands a model."""
    return exception(message="vendor said no", llm_provider="openai", model="test-model")


def _completions(
    monkeypatch: pytest.MonkeyPatch, outcomes: dict[str, Exception | str]
) -> list[str]:
    """Answer each provider by name and record the order they were probed in."""
    probed: list[str] = []

    def fake(_prompt: str, *, provider: AIProvider, **_options: int) -> str:
        probed.append(provider.name)
        answer = outcomes[provider.name]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr("apps.ai.services.provider_configuration.chat_completion", fake)
    return probed


def test_a_rate_limited_vendor_leaves_the_gate_passing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Today's spent allowance is not a fault in the restore, so it must not fail it."""
    _provider("Busy")
    _provider("Healthy")
    probed = _completions(monkeypatch, {"Busy": _refusal(RateLimitError), "Healthy": "ready"})

    assert check_ai_providers.main() == 0

    assert probed == ["Busy", "Healthy"]
    output = capsys.readouterr().out
    assert "Busy: NOT PROVEN" in output
    assert "Healthy: verified" in output


def test_a_rejected_credential_fails_the_gate_after_every_vendor_is_probed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Misconfiguration must fail the restore, and name every vendor in one run."""
    _provider("Wrong key")
    _provider("Healthy")
    probed = _completions(
        monkeypatch, {"Wrong key": _refusal(AuthenticationError), "Healthy": "ready"}
    )

    assert check_ai_providers.main() == 1

    assert probed == ["Wrong key", "Healthy"]
    output = capsys.readouterr().out
    assert "Wrong key: REJECTED" in output
    assert "Healthy: verified" in output
    assert "rejected configuration on Wrong key" in output
