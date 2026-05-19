#!/usr/bin/env python
"""Verify that Xero's create_contacts API preserves submission order.

The bulk_create_contacts_in_xero path in apps/workflow/api/xero/push.py
maps response contacts back to local Client rows by zip-by-index. That
is correct iff Xero echoes contacts back in the same order they were
sent. The Xero SDK does not document this guarantee, so we validate it
on demand against a real dev tenant.

Usage:
    python scripts/integration/verify_xero_batch_order.py [--count 10]

Run before relying on bulk_create_contacts_in_xero (e.g. after a Xero
API release, or quarterly as a health check). Exits 0 on pass; non-zero
with a diagnostic on fail. Cleans up by archiving every contact it
created, so the script is safe to re-run.
"""

import argparse
import logging
import os
import sys
import time
import uuid

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from xero_python.accounting import AccountingApi
from xero_python.accounting.models import Contact

from apps.workflow.api.xero.auth import api_client, get_tenant_id

SLEEP_TIME = 1

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("verify_xero_batch_order")


def build_contacts(count: int, run_token: str) -> list[Contact]:
    """Build N contacts with names that are unique within this run AND
    unique across runs (run_token disambiguates parallel/repeated runs)."""
    return [
        Contact(name=f"Verify Xero Order {run_token} {i:04d}") for i in range(count)
    ]


def archive(accounting_api: AccountingApi, tenant_id: str, contacts) -> None:
    """Best-effort cleanup: archive every contact we created so the dev
    tenant doesn't accumulate test rows on repeated runs. Failures here
    don't change the script's exit code — we want the assertion result
    to dominate."""
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
        except Exception as exc:
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

    accounting_api = AccountingApi(api_client)
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
            for i, (s, r) in enumerate(zip(sent, received))
            if s.name != r.name
        ]

        if mismatches:
            logger.error(
                "FAIL: Xero response is NOT in submission order. "
                "Do NOT rely on zip-by-index in bulk_create_contacts_in_xero. "
                "Switch to a correlator-based mapping (e.g. contact_number)."
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
