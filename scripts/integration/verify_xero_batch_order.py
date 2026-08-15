#!/usr/bin/env python
"""Verify that Xero's create_contacts API preserves submission order.

INTEGRATION SCRIPT — mutates a real external system. It submits real
(distinctively named, throwaway) contacts to the connected Xero org and is
never part of the default test suite; run it by hand against a dev tenant
only. Cleanup archives every contact it created, so re-runs are safe.

bulk_create_contacts_in_xero in apps/xero/seeding.py maps response contacts
back to local Company rows by zip-by-index (with a per-name tripwire). That
is correct iff Xero echoes contacts back in the same order they were sent.
The Xero SDK does not document this guarantee, so we validate it on demand
against a real dev tenant.

Usage:
    uv run python -m scripts.integration.verify_xero_batch_order [--count 10]

Run before relying on bulk_create_contacts_in_xero (e.g. after a Xero API
release, or quarterly as a health check). Exits 0 on pass; non-zero with a
diagnostic on fail.
"""

import argparse
import logging
import sys
import time
import uuid

from scripts.bootstrap import setup_django

setup_django()

from xero_python.accounting import (  # noqa: E402 -- Django must be configured first
    AccountingApi,
    Contact,
)

from apps.xero.auth import get_api_client, get_tenant_id  # noqa: E402
from apps.xero.operator_guards import (  # noqa: E402
    assert_not_production_target,
    assert_xero_writes_enabled,
)

SLEEP_TIME = 1

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("verify_xero_batch_order")


def build_contacts(count: int, run_token: str) -> list[Contact]:
    """Build N throwaway contacts, unique within this run AND across runs.

    The run_token disambiguates parallel/repeated runs — Xero rejects
    duplicate contact names, which would abort the check.
    """
    return [Contact(name=f"Verify Xero Order {run_token} {i:04d}") for i in range(count)]


def archive(accounting_api: AccountingApi, tenant_id: str, contacts: list[Contact]) -> None:
    """Archive every contact we created so the dev tenant stays clean.

    Best-effort: failures here don't change the script's exit code — the
    ordering assertion's result must dominate.
    """
    for contact in contacts:
        if not contact.contact_id:
            continue
        try:
            accounting_api.update_contact(
                tenant_id,
                contact_id=contact.contact_id,
                contacts={
                    "contacts": [
                        Contact(
                            contact_id=contact.contact_id,
                            contact_status="ARCHIVED",
                        )
                    ]
                },
            )
            time.sleep(SLEEP_TIME)
        except Exception as exc:  # noqa: BLE001 -- deliberate-swallow: cleanup is best-effort; a stuck test contact is reported, not fatal
            logger.warning(
                "Failed to archive %s (%s): %s",
                contact.name,
                contact.contact_id,
                exc,
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="Number of contacts to submit (default: 10)",
    )
    args = parser.parse_args()

    if args.count < 2:
        logger.error("--count must be at least 2 to verify ordering")
        return 2

    # Direct SDK writes bypass the readonly provider, so both guards are
    # checked here explicitly: no fabricated ids, and never the prod org.
    assert_xero_writes_enabled("verify_xero_batch_order")
    assert_not_production_target()

    accounting_api = AccountingApi(get_api_client())
    tenant_id = get_tenant_id()
    run_token = uuid.uuid4().hex[:8]
    sent = build_contacts(args.count, run_token)

    logger.info(
        "Submitting %d contacts (run_token=%s) to tenant %s ...",
        args.count,
        run_token,
        tenant_id,
    )
    response = accounting_api.create_contacts(tenant_id, contacts={"contacts": sent})
    time.sleep(SLEEP_TIME)

    if not response or not response.contacts:
        logger.error("FAIL: empty response from create_contacts")
        return 1

    received = response.contacts

    try:
        if len(received) != len(sent):
            logger.error(
                "FAIL: sent %d contacts but received %d in response",
                len(sent),
                len(received),
            )
            return 1

        mismatches = [
            (i, s.name, r.name)
            for i, (s, r) in enumerate(zip(sent, received, strict=True))
            if s.name != r.name
        ]

        if mismatches:
            logger.error(
                "FAIL: Xero response is NOT in submission order. "
                "Do NOT rely on zip-by-index in apps/xero/seeding.py's "
                "bulk_create_contacts_in_xero. Switch to a correlator-based "
                "mapping (e.g. contact_number)."
            )
            for idx, sent_name, recv_name in mismatches[:5]:
                logger.error(
                    "  position %d: sent=%r received=%r",
                    idx,
                    sent_name,
                    recv_name,
                )
            return 1

        logger.info(
            "PASS: all %d positions match. Xero preserved submission order.",
            len(sent),
        )
        return 0
    finally:
        logger.info("Cleaning up: archiving %d test contacts ...", len(received))
        archive(accounting_api, tenant_id, received)


if __name__ == "__main__":
    sys.exit(main())
