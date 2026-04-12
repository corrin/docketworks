"""Accounting provider registry — resolves settings.ACCOUNTING_BACKEND to a provider instance."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.conf import settings

if TYPE_CHECKING:
    from .provider import AccountingProvider

logger = logging.getLogger(__name__)

_providers: dict[str, type[AccountingProvider]] = {}


def register_provider(name: str, provider_class: type[AccountingProvider]) -> None:
    """Register an accounting provider implementation."""
    _providers[name] = provider_class
    logger.info("Registered accounting provider: %s", name)


def get_provider() -> AccountingProvider:
    """Return an instance of the configured accounting provider.

    The active backend is determined by settings.ACCOUNTING_BACKEND.
    Raises RuntimeError if the backend is not registered.
    """
    backend = getattr(settings, "ACCOUNTING_BACKEND", "xero")
    if backend not in _providers:
        raise RuntimeError(
            f"Unknown accounting backend '{backend}'. "
            f"Registered providers: {sorted(_providers.keys())}"
        )
    return _providers[backend]()


def get_provider_name() -> str:
    """Return the name of the configured accounting backend."""
    return getattr(settings, "ACCOUNTING_BACKEND", "xero")


def is_accounting_enabled() -> bool:
    """Check whether accounting sync is enabled for this installation."""
    from apps.workflow.models import CompanyDefaults

    return CompanyDefaults.get_solo().enable_xero_sync
