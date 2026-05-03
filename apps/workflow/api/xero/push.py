import logging
import time
from datetime import datetime
from typing import Any, Dict

from django.conf import settings
from django.db import models
from django.utils import timezone
from xero_python.accounting import AccountingApi
from xero_python.project.models import TimeEntryCreateOrUpdate

from apps.accounts.models import Staff
from apps.job.models.costing import CostLine
from apps.workflow.api.xero.auth import api_client, get_tenant_id
from apps.workflow.api.xero.xero import (
    create_default_task,
    create_project,
    update_project,
)

logger = logging.getLogger("xero")

SLEEP_TIME = 1  # Sleep after every API call to avoid hitting rate limits


def sync_client_to_xero(client):
    """Push a client to Xero"""
    if not client.validate_for_xero():
        logger.error(f"Client {client.id} failed validation")
        return False

    accounting_api = AccountingApi(api_client)
    contact_data = client.get_client_for_xero()

    if not contact_data:
        logger.error(f"Client {client.id} failed to generate Xero data")
        return False

    if client.xero_contact_id:
        contact_data["ContactID"] = client.xero_contact_id
        response = accounting_api.update_contact(
            get_tenant_id(),
            contact_id=client.xero_contact_id,
            contacts={"contacts": [contact_data]},
        )
        time.sleep(SLEEP_TIME)
        logger.info(f"Updated client {client.name} in Xero")
    else:
        response = accounting_api.create_contacts(
            get_tenant_id(), contacts={"contacts": [contact_data]}
        )
        time.sleep(SLEEP_TIME)
        client.xero_contact_id = response.contacts[0].contact_id
        client.save()
        logger.info(
            f"Created client {client.name} in Xero with ID {client.xero_contact_id}"
        )

    return True


def sync_job_to_xero(job):
    """Push a job to Xero Projects API"""
    from apps.workflow.api.xero.transforms import get_or_fetch_client

    if not settings.XERO_SYNC_PROJECTS:
        logger.info(
            f"Skipping Xero Project sync for Job {job.job_number} "
            "(feature flag disabled)"
        )
        return False

    logger.info(f"Syncing Job {job.job_number} ({job.name}) to Xero")

    # Validation
    if not job.client:
        logger.error(f"Job {job.job_number} has no client - cannot sync to Xero")
        return False

    if not job.client.xero_contact_id:
        logger.error(
            f"Job {job.job_number} client '{job.client.name}' has no xero_contact_id - sync client first"
        )
        return False

    # Validate contact exists in Xero - fail early
    try:
        valid_client = get_or_fetch_client(
            job.client.xero_contact_id, f"job {job.job_number}"
        )
        logger.info(f"Validated client exists in Xero: {valid_client.name}")
    except Exception as e:
        logger.error(
            f"Job {job.job_number} client contact_id {job.client.xero_contact_id} does not exist in Xero: {e}"
        )
        return False

    # Prepare project data
    # Include job number in name to ensure uniqueness (multiple jobs can have same name)
    sanitized_name = job.name.replace("<", "(").replace(">", ")") if job.name else ""
    project_name = (
        f"Job {job.job_number}: {sanitized_name}"
        if sanitized_name
        else f"Job {job.job_number}"
    )
    project_data = {
        "name": project_name,
        "contact_id": job.client.xero_contact_id,
    }

    # Add optional fields (correct field names per SDK) - defensive programming
    if not job.delivery_date:
        # Skip deadline - it's optional in Xero
        pass
    else:
        # Convert date to timezone-aware datetime at end of day
        delivery_datetime = timezone.make_aware(
            datetime.combine(job.delivery_date, datetime.max.time())
        )
        project_data["deadline_utc"] = delivery_datetime

    # TODO: description not supported in ProjectCreateOrUpdate - set via separate API call
    # if job.description:
    #     project_data["description"] = job.description

    # TODO: status not supported in ProjectCreateOrUpdate - set via separate API call
    # # Map job status to Xero project status
    # # Most statuses → INPROGRESS, only "archived" → CLOSED
    # if job.status == "archived":
    #     project_data["status"] = "CLOSED"
    # else:
    #     project_data["status"] = "INPROGRESS"

    # Handle estimate from latest_estimate - defensive programming
    if not job.latest_estimate:
        raise ValueError(f"Job {job.job_number} has no latest_estimate")

    estimate_total = job.latest_estimate.total_revenue
    # Only set estimate_amount if greater than 0 (Xero requirement)
    if estimate_total and float(estimate_total) > 0:
        project_data["estimate_amount"] = float(estimate_total)

    try:
        if job.xero_project_id:
            # Update existing project
            logger.info(f"Updating existing Xero project {job.xero_project_id}")
            response = update_project(job.xero_project_id, project_data)
            time.sleep(SLEEP_TIME)
            logger.info(f"Updated Job {job.job_number} project in Xero")
        else:
            # Create new project
            logger.info(f"Creating new Xero project for Job {job.job_number}")
            response = create_project(project_data)
            time.sleep(SLEEP_TIME)

            # Save the project ID back to our job
            automation_user = Staff.get_automation_user()
            job.xero_project_id = response.project_id
            job.xero_last_synced = timezone.now()
            job.save(
                staff=automation_user,
                update_fields=["xero_project_id", "xero_last_synced"],
            )

            logger.info(
                f"Created Job {job.job_number} in Xero with project ID {job.xero_project_id}"
            )

            # Create default Labor task for time entries
            logger.info(f"Creating default Labor task for Job {job.job_number}")
            default_task = create_default_task(job.xero_project_id)
            time.sleep(SLEEP_TIME)

            job.xero_default_task_id = default_task.task_id
            job.save(staff=automation_user, update_fields=["xero_default_task_id"])

            logger.info(
                f"Created default Labor task for Job {job.job_number} with task ID {job.xero_default_task_id}"
            )

        # Sync CostLine time/expense entries in bulk
        if job.xero_project_id:
            sync_costlines_to_xero(job)

        return True

    except Exception as e:
        logger.error(f"Failed to sync Job {job.job_number} to Xero: {e}", exc_info=True)
        return False


def sync_costlines_to_xero(job) -> bool:
    """
    Sync job CostLines to Xero Projects as time entries and expense tasks.

    Time CostLines (kind='time') -> Xero time entries with default task
    Other CostLines (material/adjust) -> Xero tasks with FIXED charge type

    Only syncs CostLines from 'actual' cost sets that have been modified
    since last sync or never synced before.
    """
    logger.info(f"Syncing CostLines for Job {job.job_number} to Xero")

    if not job.xero_project_id:
        error = ValueError(f"Job {job.job_number} has no xero_project_id")
        raise error

    # Get CostLines from actual cost sets only
    actual_cost_sets = job.cost_sets.filter(kind="actual")
    if not actual_cost_sets.exists():
        logger.info(f"Job {job.job_number} has no actual cost sets - nothing to sync")
        return True

    costlines = CostLine.objects.filter(cost_set__in=actual_cost_sets).filter(
        models.Q(xero_last_synced__isnull=True)
        | models.Q(xero_last_modified__gt=models.F("xero_last_synced"))
    )

    if not costlines.exists():
        logger.info(f"Job {job.job_number} has no CostLines needing sync")
        return True

    logger.info(f"Found {costlines.count()} CostLines to sync for Job {job.job_number}")

    # Separate time entries from expenses
    time_entries = []
    expense_entries = []

    for costline in costlines:
        if costline.kind == "time":
            time_entry = map_costline_to_time_entry(costline, job.xero_default_task_id)
            time_entries.append((costline, time_entry))
        else:
            expense_entry = map_costline_to_expense_entry(costline)
            expense_entries.append((costline, expense_entry))

    # Sync time entries
    if time_entries:
        sync_time_entries_bulk(job.xero_project_id, time_entries)

    # Sync expense entries
    if expense_entries:
        sync_expense_entries_bulk(job.xero_project_id, expense_entries)

    logger.info(f"Completed CostLine sync for Job {job.job_number}")
    return True


def map_costline_to_time_entry(costline, task_id: str) -> TimeEntryCreateOrUpdate:
    """
    Map a CostLine (kind='time') to Xero TimeEntryCreateOrUpdate object.

    Converts hours (quantity) to minutes, validates staff reference in meta,
    and creates proper Xero Python library object for API calls.
    """
    staff_id = costline.meta.get("staff_id")
    if not staff_id:
        error = ValueError(f"CostLine {costline.id} has no staff_id in meta")
        raise error

    try:
        Staff.objects.get(id=staff_id)
    except Staff.DoesNotExist:
        error = ValueError(
            f"CostLine {costline.id} references non-existent staff {staff_id}"
        )
        raise error

    # Convert hours to minutes (Xero uses minutes)
    if costline.quantity is None:
        error = ValueError(f"CostLine {costline.id} has null quantity")
        raise error

    minutes = int(float(costline.quantity) * 60)

    # Get date from accounting_date field - must exist
    if not costline.accounting_date:
        error = ValueError(f"CostLine {costline.id} has no accounting_date")
        raise error

    date_utc = datetime.combine(costline.accounting_date, datetime.min.time())

    time_entry = TimeEntryCreateOrUpdate(
        description=costline.desc,
        duration=minutes,
        date_utc=date_utc,
        user_id=settings.XERO_DEFAULT_USER_ID,  # This is supposed to be the staff ID.  The code here is wrong.
        task_id=task_id,
    )

    # Skip user_id - let Xero assign to current token user

    # Include existing Xero time ID if updating
    if costline.xero_time_id:
        time_entry.time_entry_id = costline.xero_time_id

    return time_entry


def map_costline_to_expense_entry(costline) -> Dict[str, Any]:
    """
    Map a CostLine (material/adjust) to Xero task dictionary format.

    Creates FIXED charge type tasks with calculated total amount.
    These become expense tasks in Xero Projects.
    """
    if costline.quantity is None:
        error = ValueError(f"CostLine {costline.id} has null quantity")
        raise error

    if costline.unit_cost is None:
        error = ValueError(f"CostLine {costline.id} has null unit_cost")
        raise error

    # Calculate total amount
    total_amount = float(costline.quantity) * float(costline.unit_cost)

    expense_entry = {
        "name": costline.desc,
        "chargeType": "FIXED",
        "rate": {
            "currency": "NZD",  # NZD is correct for this NZ business
            "value": total_amount,
        },
    }

    # Include existing Xero task ID if updating
    if costline.xero_expense_id:
        expense_entry["task_id"] = costline.xero_expense_id

    return expense_entry


def sync_time_entries_bulk(project_id, time_entries_list):
    """Sync multiple time entries to Xero in bulk"""
    from .xero import create_time_entries, update_time_entries

    create_entries = []
    update_entries = []
    create_costlines = []
    update_costlines = []

    for costline, time_entry in time_entries_list:
        if costline.xero_time_id:
            update_entries.append(time_entry)
            update_costlines.append(costline)
        else:
            create_entries.append(time_entry)
            create_costlines.append(costline)

    # Create new entries
    if create_entries:
        logger.info(f"Creating {len(create_entries)} time entries")
        created = create_time_entries(project_id, create_entries)

        # Validate API response
        if len(created) != len(create_costlines):
            error = ValueError(
                f"Xero returned {len(created)} time entries but expected {len(create_costlines)}"
            )
            raise error

        # Update CostLines with returned Xero IDs
        for i, xero_entry in enumerate(created):
            costline = create_costlines[i]
            costline.xero_time_id = xero_entry.time_entry_id
            costline.xero_last_synced = timezone.now()
            costline.save(update_fields=["xero_time_id", "xero_last_synced"])

    # Update existing entries
    if update_entries:
        logger.info(f"Updating {len(update_entries)} time entries")
        update_time_entries(project_id, update_entries)
        # Update sync timestamps
        for costline in update_costlines:
            costline.xero_last_synced = timezone.now()
            costline.save(update_fields=["xero_last_synced"])


def sync_expense_entries_bulk(project_id, expense_entries_list):
    """Sync multiple expense entries to Xero in bulk"""
    from .xero import create_expense_entries, update_expense_entries

    create_entries = []
    update_entries = []
    create_costlines = []
    update_costlines = []

    for costline, expense_entry in expense_entries_list:
        if costline.xero_expense_id:
            update_entries.append(expense_entry)
            update_costlines.append(costline)
        else:
            create_entries.append(expense_entry)
            create_costlines.append(costline)

    # Create new entries
    if create_entries:
        logger.info(f"Creating {len(create_entries)} expense entries")
        created = create_expense_entries(project_id, create_entries)

        # Validate API response
        if len(created) != len(create_costlines):
            error = ValueError(
                f"Xero returned {len(created)} expense entries but expected {len(create_costlines)}"
            )
            raise error

        # Update CostLines with returned Xero task IDs
        for i, xero_entry in enumerate(created):
            costline = create_costlines[i]
            costline.xero_expense_id = xero_entry.task_id
            costline.xero_last_synced = timezone.now()
            costline.save(update_fields=["xero_expense_id", "xero_last_synced"])

    # Update existing entries
    if update_entries:
        logger.info(f"Updating {len(update_entries)} expense entries")
        update_expense_entries(project_id, update_entries)
        # Update sync timestamps
        for costline in update_costlines:
            costline.xero_last_synced = timezone.now()
            costline.save(update_fields=["xero_last_synced"])


def get_all_xero_contacts():
    """Fetch all contacts from Xero (including archived)"""
    accounting_api = AccountingApi(api_client)
    all_contacts = []

    try:
        # Get all contacts (including archived)
        response = accounting_api.get_contacts(get_tenant_id(), include_archived=True)
        time.sleep(SLEEP_TIME)

        for contact in response.contacts:
            all_contacts.append(
                {"name": contact.name, "contact_id": contact.contact_id}
            )
            # TODO: REMOVE DEBUG - Log specific contacts we're looking for
            if contact.name in ["Johnson PLC", "Martinez LLC"]:
                logger.info(
                    f"DEBUG: Found existing contact '{contact.name}' with ID {contact.contact_id}"
                )

        # TODO: REMOVE DEBUG - Summary of what we fetched
        logger.info(f"DEBUG: Fetched {len(all_contacts)} total contacts from Xero")

    except Exception as e:
        logger.error(f"Error fetching existing contacts from Xero: {e}")
        raise

    return all_contacts


def create_client_contact_in_xero(client):
    """Create a single client as Xero contact. Returns xero_contact_id on success, raises on failure."""
    if not client.validate_for_xero():
        raise ValueError(f"Client {client.id} failed Xero validation")

    accounting_api = AccountingApi(api_client)
    contact_data = client.get_client_for_xero()

    if not contact_data:
        raise ValueError(f"Client {client.id} failed to generate Xero data")

    response = accounting_api.create_contacts(
        get_tenant_id(), contacts={"contacts": [contact_data]}
    )
    time.sleep(SLEEP_TIME)

    if not response or not response.contacts:
        raise ValueError(
            f"Xero API returned empty response when creating contact for client {client.id}"
        )

    client.xero_contact_id = str(response.contacts[0].contact_id)
    client.save(update_fields=["xero_contact_id"])
    return client.xero_contact_id


def bulk_create_contacts_in_xero(clients_to_create, batch_size=50):
    """Create multiple client contacts in Xero in batches of 50"""
    if not clients_to_create:
        return 0

    accounting_api = AccountingApi(api_client)

    total_created = 0

    for i in range(0, len(clients_to_create), batch_size):
        batch = clients_to_create[i : i + batch_size]

        # Prepare batch contact data
        contact_batch = []
        batch_client_map = {}  # Map contact name to client object

        for client in batch:
            if not client.validate_for_xero():
                logger.error(f"Client {client.name} failed Xero validation")
                raise ValueError(
                    f"Client {client.name} failed Xero validation"
                )  # FAIL EARLY

            contact_data = client.get_client_for_xero()
            if not contact_data:
                logger.error(f"Client {client.name} failed to generate Xero data")
                raise ValueError(
                    f"Client {client.name} failed to generate Xero data"
                )  # FAIL EARLY

            # FAIL EARLY: Validate required fields
            if "name" not in contact_data:
                logger.error(
                    f"Client {client.name} contact data missing 'name' field: {contact_data}"
                )
                raise ValueError(
                    f"Client {client.name} contact data missing 'name' field"
                )  # FAIL EARLY

            # Convert lowercase 'name' to uppercase 'Name' for Xero API
            if "Name" not in contact_data and "name" in contact_data:
                contact_data["Name"] = contact_data["name"]
                del contact_data["name"]

            contact_batch.append(contact_data)
            batch_client_map[contact_data["Name"]] = client

        if not contact_batch:
            logger.warning(f"No valid contacts in batch {i // batch_size + 1}")
            continue

        try:
            # Single API call for up to 50 contacts
            logger.info(
                f"Creating batch of {len(contact_batch)} contacts in Xero (batch {i // batch_size + 1})"
            )
            response = accounting_api.create_contacts(
                get_tenant_id(), contacts={"contacts": contact_batch}
            )

            # FAIL EARLY: Check for API errors before sleeping
            if not response or not response.contacts:
                raise ValueError(
                    f"Xero API returned empty response for batch {i // batch_size + 1}"
                )

            time.sleep(
                SLEEP_TIME
            )  # Single sleep for the entire batch - only after success

            # Process responses and update client records
            for created_contact in response.contacts:
                contact_name = created_contact.name
                if contact_name in batch_client_map:
                    client = batch_client_map[contact_name]
                    client.xero_contact_id = created_contact.contact_id
                    client.save(update_fields=["xero_contact_id"])
                    total_created += 1
                    logger.info(
                        f"Created Xero contact for client {client.name}: {client.xero_contact_id}"
                    )
                else:
                    logger.warning(
                        f"Could not map created contact '{contact_name}' back to client"
                    )

        except Exception as e:
            logger.error(
                f"Failed to create batch of {len(contact_batch)} contacts: {e}"
            )
            raise  # FAIL EARLY

    return total_created
