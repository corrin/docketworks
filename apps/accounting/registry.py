"""Accounting provider registry — resolves CompanyDefaults.accounting_provider.

Providers register themselves at app-ready (apps/xero/apps.py); this module
never imports an implementation. That inversion is what lets the domain layer
call accounting operations while the Xero code lives above it in the layer
contract.
"""

import logging
from typing import TYPE_CHECKING

from django.conf import settings

if TYPE_CHECKING:
    from .provider import AccountingProvider

logger = logging.getLogger(__name__)

_providers: dict[str, "type[AccountingProvider]"] = {}


def register_provider(name: str, provider_class: "type[AccountingProvider]") -> None:
    """Register an accounting provider implementation."""
    _providers[name] = provider_class
    logger.debug("Registered accounting provider: %s", name)


def get_provider() -> "AccountingProvider":
    """Return an instance of the configured accounting provider.

    The active backend is determined by CompanyDefaults.accounting_provider.
    When settings.XERO_READONLY is set (process-scoped, E2E/test backends
    only) the Xero backend is swapped for its write-suppressing variant.
    Raises RuntimeError if the backend is not registered.
    """
    backend = get_provider_name()
    if settings.XERO_READONLY and backend == "xero":
        backend = "xero_readonly"
    if backend not in _providers:
        raise RuntimeError(
            f"Unknown accounting backend '{backend}'. "
            f"Registered providers: {sorted(_providers.keys())}"
        )
    return _providers[backend]()


def is_accounting_enabled() -> bool:
    """Report whether accounting sync is enabled for this installation."""
    # Call-time import, as get_provider_name explains.
    from apps.core.models import CompanyDefaults  # noqa: PLC0415

    enabled: bool = CompanyDefaults.get_solo().enable_xero_sync
    return enabled


def get_provider_name() -> str:
    """Return the name of the configured accounting backend."""
    # Call-time import: this module is imported before Django's app registry
    # is ready (service modules import get_provider at module scope).
    from apps.core.models import CompanyDefaults  # noqa: PLC0415

    name: str = CompanyDefaults.get_solo().accounting_provider
    return name
