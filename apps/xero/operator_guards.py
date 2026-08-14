"""Refusals that protect a real Xero organisation from operator tooling.

The setup/seed/sync commands write directly to whichever organisation the
installation is currently connected to. Both guards here answer the same
question — "is this run pointed somewhere it must never write?" — and both
refuse loudly rather than degrading, because a partial run against the wrong
target is discovered days later as duplicated or fabricated records.
"""

import logging

from django.conf import settings

from apps.xero.auth import get_tenant_id

logger = logging.getLogger(__name__)


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


def assert_not_production_target() -> None:
    """Refuse to run against a production database or the production Xero org.

    Two independent checks because either one alone has a hole: the database
    name is checked before any credential is needed, and the tenant check
    catches a non-prod database that has been pointed at the live Xero org
    (which is how a seed would write fabricated ids into real accounts).
    """
    db_name = str(settings.DATABASES["default"]["NAME"])
    # The `dw_<company>_<env>` naming standard validates env against
    # {dev,uat,staging,prod}, so the `_prod` suffix is a deterministic
    # instance-scoped signal — it works on multi-instance servers where
    # /etc/machine-id is shared.
    if db_name.endswith("_prod"):
        raise ValueError(
            f"Refusing to seed Xero against production database: {db_name}. "
            "This operation is only for development environments after a production restore."
        )

    tenant_id = get_tenant_id()
    if tenant_id == settings.PRODUCTION_XERO_TENANT_ID:
        raise ValueError(
            f"Refusing to seed Xero against the production Xero tenant ({tenant_id}). "
            "Connect the instance to its own demo/UAT organisation first."
        )
