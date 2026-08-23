"""Refusals that protect a real Xero organisation from operator tooling.

The setup/seed/sync commands write directly to whichever organisation the
installation is currently connected to. Both guards here answer the same
question — "is this run pointed somewhere it must never write?" — and both
refuse loudly rather than degrading, because a partial run against the wrong
target is discovered days later as duplicated or fabricated records.
"""

import logging

from django.conf import settings

from apps.core.environment import assert_not_production_database
from apps.xero.auth import get_tenant_id

logger = logging.getLogger(__name__)


def is_production_tenant(tenant_id: str) -> bool:
    """Return whether this tenant is a production organisation — the one implementation.

    Keyed only on the hardcoded per-client list (see config/settings.py for
    why it is code, not env). Callers layer their own deployment policy on
    top; they never re-derive membership.
    """
    return tenant_id in settings.PRODUCTION_XERO_TENANT_IDS


def assert_xero_writes_enabled(operation: str) -> None:
    """Refuse an operator write when ``settings.XERO_READONLY`` is set.

    The readonly provider suppresses writes and returns fabricated ids for
    callers that need a result object. That is right for E2E, and exactly
    wrong here: these commands exist to REPAIR the mirror, so fabricated ids
    written into it produce the corruption they were run to fix.
    """
    if settings.XERO_READONLY:
        # "Unset XERO_READONLY" would be the natural remedy to name, but the
        # variable is in REQUIRED_ENV_VARS: with it unset every manage.py
        # invocation dies at startup, so the only working remedy is the
        # explicit false value.
        raise RuntimeError(
            f"XERO_READONLY is set: refusing to run {operation}. This command writes to "
            f"Xero and would store fabricated ids in the local mirror. Set "
            f"XERO_READONLY=false for this run."
        )


def assert_not_production_target(tenant_id: str | None = None) -> None:
    """Refuse to run against a production database or a production Xero org.

    Two independent checks because either one alone has a hole: the database
    name is checked before any credential is needed, and the tenant check
    catches a non-prod database that has been pointed at the live Xero org
    (which is how a seed would write fabricated ids into real accounts).

    ``tenant_id`` overrides the configured tenant, for the one caller that is
    about to REBIND: ``manage.py xero --setup`` discovers the connected org
    and must be judged on that, because the stored value is the org it is
    leaving. Everyone else is already bound and omits it.
    """
    assert_not_production_database(
        "Xero seeding writes to whichever organisation this installation is "
        "connected to, and is only for a development environment after a "
        "production restore."
    )

    if tenant_id is None:
        tenant_id = get_tenant_id()
    if is_production_tenant(tenant_id):
        raise ValueError(
            f"Refusing to seed Xero against a production Xero tenant ({tenant_id}). "
            "Connect the instance to its own demo/UAT organisation first."
        )
