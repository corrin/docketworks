"""Explicit delegation identity and locally knowable credential refusals."""

from unittest.mock import Mock

import pytest

from apps.platform.integrations.google import credentials


@pytest.mark.parametrize("company_email", [None, "company@example.com"])
def test_environment_override_selects_the_workspace_user(
    monkeypatch: pytest.MonkeyPatch, company_email: str | None
) -> None:
    monkeypatch.setenv("GCP_DELEGATED_SUBJECT", "workspace@example.com")
    assert credentials.delegated_subject(company_email) == "workspace@example.com"


def test_company_address_is_used_when_no_override_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GCP_DELEGATED_SUBJECT", raising=False)
    assert credentials.delegated_subject("company@example.com") == "company@example.com"


def test_missing_identity_is_not_a_service_account_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GCP_DELEGATED_SUBJECT", raising=False)
    with pytest.raises(RuntimeError):
        credentials.delegated_subject(None)


def test_empty_explicit_subject_is_refused_before_loading_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load = Mock()
    monkeypatch.setattr(credentials, "service_account_credentials", load)
    monkeypatch.setenv("GCP_DELEGATED_SUBJECT", "company@example.com")
    with pytest.raises(ValueError):
        credentials.delegated_credentials(["scope"], "")
    load.assert_not_called()


def test_explicit_mailbox_is_not_replaced_by_company_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load = Mock()
    monkeypatch.setattr(credentials, "service_account_credentials", load)
    monkeypatch.setenv("GCP_DELEGATED_SUBJECT", "company@example.com")
    credentials.delegated_credentials(["scope"], "person@example.com")
    load.assert_called_once_with(["scope"])
    load.return_value.with_subject.assert_called_once_with("person@example.com")
