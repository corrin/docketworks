import logging
import time

from django.utils import timezone
from xero_python.accounting import AccountingApi

from apps.accounting.models import Bill, Invoice
from apps.client.models import Client
from apps.workflow.api.xero.auth import api_client, get_tenant_id
from apps.workflow.api.xero.push import (
    bulk_create_contacts_in_xero,
    get_all_xero_contacts,
    sync_job_to_xero,
)
from apps.workflow.api.xero.reprocess_xero import (
    set_client_fields,
    set_invoice_or_bill_fields,
)
from apps.workflow.api.xero.transforms import process_xero_data, transform_pay_run

SLEEP_TIME = 1  # Sleep after every API call to avoid hitting rate limits

logger = logging.getLogger("xero")


def seed_clients_to_xero(clients):
    """Bulk process clients: link existing contacts + create missing ones in batches of 50"""
    # Get all existing Xero contacts (one API call)
    try:
        existing_contacts = get_all_xero_contacts()
    except Exception as e:
        logger.error(f"Failed to fetch existing Xero contacts: {e}")
        raise  # FAIL EARLY

    existing_names = {
        contact["name"].lower(): contact["contact_id"] for contact in existing_contacts
    }

    results = {"linked": 0, "created": 0, "failed": []}

    # Separate clients into link vs create lists
    clients_to_link = []
    clients_to_create = []

    # TODO: REMOVE DEBUG - Temporary debugging for duplicate contact issue
    logger.info(
        f"DEBUG: Found {len(existing_names)} existing contacts in Xero for matching"
    )

    for client in clients:
        if client.name.lower() in existing_names:
            clients_to_link.append((client, existing_names[client.name.lower()]))
            # TODO: REMOVE DEBUG
            logger.info(
                f"DEBUG: Will LINK '{client.name}' to existing contact {existing_names[client.name.lower()]}"
            )
        else:
            clients_to_create.append(client)
            # TODO: REMOVE DEBUG - Log clients that will be created (potential duplicates)
            if client.name in ["Johnson PLC", "Martinez LLC"]:
                logger.warning(
                    f"DEBUG: Will CREATE '{client.name}' - not found in existing contacts"
                )
                logger.warning(
                    f"DEBUG: Available existing contact names: {sorted(list(set([name for name in existing_names.keys() if 'johnson' in name.lower() or 'martinez' in name.lower()])))}"
                )

    # TODO: REMOVE DEBUG
    logger.info(
        f"DEBUG: Final separation - {len(clients_to_link)} to link, {len(clients_to_create)} to create"
    )

    # Process linking (fast, no API calls)
    for client, existing_contact_id in clients_to_link:
        try:
            client.xero_contact_id = existing_contact_id
            client.save(update_fields=["xero_contact_id"])
            results["linked"] += 1
            logger.info(
                f"Linked client {client.name} to existing Xero contact: {existing_contact_id}"
            )
        except Exception as e:
            logger.error(f"Error linking client {client.name}: {e}")
            raise  # FAIL EARLY

    # Process creation in batches using dedicated function
    if clients_to_create:
        results["created"] = bulk_create_contacts_in_xero(clients_to_create)

    return results


def seed_jobs_to_xero(jobs):
    """Bulk process jobs: create Xero projects"""
    results = {"created": 0, "failed": []}

    for job in jobs:
        try:
            # Use existing sync_job_to_xero function for consistency
            success = sync_job_to_xero(job)
            if success:
                results["created"] += 1
                logger.info(
                    f"Created Xero project for job {job.name}: {job.xero_project_id}"
                )
            else:
                logger.error(f"Failed to create Xero project for job {job.name}")
                raise Exception(
                    f"Failed to create Xero project for job {job.name}"
                )  # FAIL EARLY

        except Exception as e:
            logger.error(f"Error processing job {job.name}: {e}")
            raise  # FAIL EARLY

    return results


def sync_single_contact(sync_service, contact_id):
    """Fetch and sync a single contact from Xero by ID"""
    if not contact_id:
        raise ValueError("No contact_id provided")

    accounting_api = AccountingApi(api_client)
    response = accounting_api.get_contacts(
        sync_service.tenant_id, i_ds=[contact_id], include_archived=True
    )
    time.sleep(SLEEP_TIME)

    if not response or not response.contacts:
        raise ValueError(f"No contact found with ID {contact_id}")

    contact = response.contacts[0]
    raw_json = process_xero_data(contact)

    client, created = Client.objects.update_or_create(
        xero_contact_id=contact.contact_id,
        defaults={
            "raw_json": raw_json,
            "xero_last_modified": timezone.now(),
            "xero_archived": contact.contact_status == "ARCHIVED",
            "xero_merged_into_id": getattr(contact, "merged_to_contact_id", None),
        },
    )

    set_client_fields(client, new_from_xero=created)

    # Handle merge if needed
    if client.xero_merged_into_id and not client.merged_into:
        merged_into = Client.objects.filter(
            xero_contact_id=client.xero_merged_into_id
        ).first()
        if merged_into:
            client.merged_into = merged_into
            client.allow_jobs = False
            client.save()

    logger.info(f"Synced contact {contact_id} from webhook")


def sync_single_invoice(sync_service, invoice_id):
    """Fetch and sync a single invoice from Xero by ID"""
    if not invoice_id:
        raise ValueError("No invoice_id provided")

    accounting_api = AccountingApi(api_client)
    response = accounting_api.get_invoice(sync_service.tenant_id, invoice_id=invoice_id)
    time.sleep(SLEEP_TIME)

    if not response or not response.invoices:
        raise ValueError(f"No invoice found with ID {invoice_id}")

    xero_invoice = response.invoices[0]

    # Route to correct model based on type
    if xero_invoice.type == "ACCPAY":
        # It's a bill
        raw_json = process_xero_data(xero_invoice)
        bill, created = Bill.objects.update_or_create(
            xero_id=xero_invoice.invoice_id,
            defaults={
                "raw_json": raw_json,
                "xero_last_modified": xero_invoice._updated_date_utc,
                "xero_last_synced": timezone.now(),
            },
        )
        set_invoice_or_bill_fields(bill, "BILL", new_from_xero=created)
        logger.info(f"Synced bill {invoice_id} from webhook")

    elif xero_invoice.type == "ACCREC":
        # It's an invoice
        raw_json = process_xero_data(xero_invoice)
        invoice, created = Invoice.objects.update_or_create(
            xero_id=xero_invoice.invoice_id,
            defaults={
                "raw_json": raw_json,
                "xero_last_modified": xero_invoice._updated_date_utc,
                "xero_last_synced": timezone.now(),
            },
        )
        set_invoice_or_bill_fields(invoice, "INVOICE", new_from_xero=created)
        logger.info(f"Synced invoice {invoice_id} from webhook")
    else:
        raise ValueError(f"Unknown invoice type {xero_invoice.type} for {invoice_id}")


def sync_single_pay_run(pay_run_id):
    """Fetch and sync a single pay run from Xero by ID.

    Args:
        pay_run_id: UUID of the pay run in Xero.

    Returns:
        The synced XeroPayRun instance.
    """
    from apps.workflow.api.xero.payroll import get_pay_run

    if not pay_run_id:
        raise ValueError("No pay_run_id provided")

    xero_pay_run = get_pay_run(pay_run_id)
    if not xero_pay_run:
        raise ValueError(f"No pay run found with ID {pay_run_id}")

    pay_run, status = transform_pay_run(xero_pay_run, pay_run_id)
    logger.info(f"Synced pay run {pay_run_id}: {status}")
    return pay_run


def fetch_xero_entity_lookup(entity_name, key_func, value_func):
    """Fetch all entities from Xero, return {key_func(item): value_func(item)}.

    Uses ENTITY_CONFIGS for API method resolution, pagination, and params.
    For idempotent seed operations that need to detect already-created entities.
    """
    from apps.workflow.api.xero.sync import ENTITY_CONFIGS, _resolve_api_method

    xero_type, _, _, api_method, _, config_params, pagination_mode = ENTITY_CONFIGS[
        entity_name
    ]

    api_func = _resolve_api_method(api_method)

    xero_tenant_id = get_tenant_id()
    params = {"xero_tenant_id": xero_tenant_id}

    page_size = 100
    if pagination_mode == "page" and xero_type not in ["quotes", "accounts"]:
        params.update({"page_size": page_size})
    if config_params:
        params.update(config_params)

    lookup = {}
    page = 1

    while True:
        if pagination_mode == "page":
            params["page"] = page

        entities = api_func(**params)

        if entities is None:
            raise ValueError(f"API returned None for {entity_name}")

        items = entities if isinstance(entities, list) else getattr(entities, xero_type)
        if not items:
            break

        for item in items:
            lookup[key_func(item)] = value_func(item)

        logger.info(f"Fetched {len(items)} {entity_name} (total: {len(lookup)})")

        if len(items) < page_size or pagination_mode == "single":
            break
        page += 1

    return lookup
