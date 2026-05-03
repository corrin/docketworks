import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from xero_python.accounting import AccountingApi
from xero_python.project import ProjectApi
from xero_python.project.models import (
    Amount,
    ChargeType,
    CurrencyCode,
    ProjectCreateOrUpdate,
    TaskCreateOrUpdate,
)

from apps.workflow.api.xero.auth import api_client, get_tenant_id
from apps.workflow.models import CompanyDefaults

logger = logging.getLogger("xero")


def get_xero_items(if_modified_since: Optional[datetime] = None) -> Any:
    """
    Fetches Xero Inventory Items using the Accounting API.
    Handles rate limiting and other API errors.
    """
    logger.info(f"Fetching Xero Items. If modified since: {if_modified_since}")

    tenant_id = get_tenant_id()
    accounting_api = AccountingApi(api_client)
    logger.info(f"Using tenant ID: {tenant_id}")

    # Convert string to datetime if needed
    # Hack because some items don't go through the coorrect code path
    # which has the conversion logic
    if isinstance(if_modified_since, str):
        if_modified_since = datetime.fromisoformat(
            if_modified_since.replace("Z", "+00:00")
        )

    try:
        match if_modified_since:
            case None:
                logger.info("No 'if_modified_since' provided, fetching all items.")
                items = accounting_api.get_items(xero_tenant_id=tenant_id)
            case datetime():
                logger.info(
                    f"'if_modified_since' provided: {if_modified_since.isoformat()}"
                )
                items = accounting_api.get_items(
                    xero_tenant_id=tenant_id, if_modified_since=if_modified_since
                )
            case _:
                raise ValueError(
                    f"Invalid type for 'if_modified_since': {type(if_modified_since)}. Expected datetime or None."
                )
        logger.info(f"Successfully fetched {len(items.items)} Xero Items.")
        return items.items
    except Exception as e:
        logger.error(f"Error fetching Xero Items: {e}", exc_info=True)
        raise


def get_projects(if_modified_since: Optional[datetime] = None) -> Any:
    """
    Fetches Xero Projects using the Projects API.
    Handles rate limiting and other API errors.
    """
    logger.info(f"Fetching Xero Projects. If modified since: {if_modified_since}")

    tenant_id = get_tenant_id()
    projects_api = ProjectApi(api_client)
    logger.info(f"Using tenant ID: {tenant_id}")

    # Convert string to datetime if needed
    if isinstance(if_modified_since, str):
        if_modified_since = datetime.fromisoformat(
            if_modified_since.replace("Z", "+00:00")
        )

    try:
        match if_modified_since:
            case None:
                logger.info("No 'if_modified_since' provided, fetching all projects.")
                projects = projects_api.get_projects(xero_tenant_id=tenant_id)
            case datetime():
                logger.info(
                    f"'if_modified_since' provided: {if_modified_since.isoformat()}"
                )
                projects = projects_api.get_projects(
                    xero_tenant_id=tenant_id, if_modified_since=if_modified_since
                )
            case _:
                raise ValueError(
                    f"Invalid type for 'if_modified_since': {type(if_modified_since)}. Expected datetime or None."
                )
        logger.info(f"Successfully fetched {len(projects.items)} Xero Projects.")
        return projects.items
    except Exception as e:
        logger.error(f"Error fetching Xero Projects: {e}", exc_info=True)
        raise


def create_project(project_data: Dict[str, Any]) -> Any:
    """
    Creates a new Xero Project using the Projects API.

    Args:
        project_data: Dictionary containing project information including:
            - name: Project name
            - contact_id: Xero contact ID
            - deadline: Project deadline (datetime)
            - estimate_amount: Project estimate amount (optional)

    Returns:
        Created project object
    """
    logger.info(f"Creating Xero Project with data: {project_data}")

    tenant_id = get_tenant_id()
    projects_api = ProjectApi(api_client)

    try:
        # Create ProjectCreateOrUpdate object from dictionary data
        project_obj = ProjectCreateOrUpdate(**project_data)
        logger.info(
            f"ProjectCreateOrUpdate object: name={project_obj.name}, contact_id={project_obj.contact_id}"
        )

        # Create project using the Projects API
        created_project = projects_api.create_project(
            xero_tenant_id=tenant_id, project_create_or_update=project_obj
        )
        logger.info(
            f"Successfully created Xero Project with ID: {created_project.project_id}"
        )
        return created_project
    except Exception as e:
        logger.error(f"Error creating Xero Project: {e}", exc_info=True)
        raise


def update_project(project_id: str, project_data: Dict[str, Any]) -> Any:
    """
    Updates an existing Xero Project using the Projects API.

    Args:
        project_id: Xero project ID to update
        project_data: Dictionary containing updated project information

    Returns:
        Updated project object
    """
    logger.info(f"Updating Xero Project {project_id} with data: {project_data}")

    tenant_id = get_tenant_id()
    projects_api = ProjectApi(api_client)

    try:
        # Update project using the Projects API
        updated_project = projects_api.update_project(
            xero_tenant_id=tenant_id,
            project_id=project_id,
            project_create_or_update=project_data,
        )
        logger.info(f"Successfully updated Xero Project with ID: {project_id}")
        return updated_project
    except Exception as e:
        logger.error(f"Error updating Xero Project {project_id}: {e}", exc_info=True)
        raise


def create_time_entries(
    project_id: str, time_entries_data: List[Dict[str, Any]]
) -> Any:
    """
    Creates multiple time entries for a Xero Project.

    Args:
        project_id: Xero project ID
        time_entries_data: List of dictionaries containing time entry information

    Returns:
        Created time entries
    """
    logger.info(
        f"Creating {len(time_entries_data)} time entries for Xero Project {project_id}"
    )

    tenant_id = get_tenant_id()
    projects_api = ProjectApi(api_client)

    try:
        # Create time entries one by one using the Projects API
        created_entries = []
        for time_entry_data in time_entries_data:
            created_entry = projects_api.create_time_entry(
                xero_tenant_id=tenant_id,
                project_id=project_id,
                time_entry_create_or_update=time_entry_data,  # Single object, not list
            )
            created_entries.append(created_entry)

        logger.info(
            f"Successfully created {len(created_entries)} time entries for Project {project_id}"
        )
        return created_entries
    except Exception as e:
        logger.error(
            f"Error creating time entries for Project {project_id}: {e}", exc_info=True
        )
        raise


def create_default_task(project_id: str) -> Any:
    """
    Creates a default "Labor" task for time entries in a Xero Project.

    Args:
        project_id: Xero project ID

    Returns:
        Created task object with task_id
    """
    logger.info(f"Creating default Labor task for Xero Project {project_id}")

    tenant_id = get_tenant_id()
    projects_api = ProjectApi(api_client)

    # Get charge out rate from company defaults
    company_defaults = CompanyDefaults.get_solo()

    rate_amount = Amount(
        currency=CurrencyCode.NZD, value=float(company_defaults.charge_out_rate)
    )

    task_data = TaskCreateOrUpdate(
        name="Labor", rate=rate_amount, charge_type=ChargeType.TIME
    )

    try:
        created_task = projects_api.create_task(
            xero_tenant_id=tenant_id,
            project_id=project_id,
            task_create_or_update=task_data,  # Single object, not list
        )
        logger.info(f"Successfully created default Labor task for Project {project_id}")
        return created_task
    except Exception as e:
        logger.error(
            f"Error creating default task for Project {project_id}: {e}", exc_info=True
        )
        raise


def create_expense_entries(
    project_id: str, expense_entries_data: List[Dict[str, Any]]
) -> Any:
    """
    Creates multiple expense entries for a Xero Project as tasks.

    Args:
        project_id: Xero project ID
        expense_entries_data: List of dictionaries containing expense entry information

    Returns:
        Created expense entries (as tasks)
    """
    logger.info(
        f"Creating {len(expense_entries_data)} expense entries for Xero Project {project_id}"
    )

    tenant_id = get_tenant_id()
    projects_api = ProjectApi(api_client)

    try:
        # Create expense entries as tasks using the Projects API
        created_entries = []
        for expense_entry_data in expense_entries_data:
            # Convert dict data to proper TaskCreateOrUpdate object
            rate_amount = Amount(
                currency=CurrencyCode.NZD,
                value=float(expense_entry_data["rate"]["value"]),
            )

            task_data = TaskCreateOrUpdate(
                name=expense_entry_data["name"],
                rate=rate_amount,
                charge_type=ChargeType.FIXED,
            )

            created_entry = projects_api.create_task(
                xero_tenant_id=tenant_id,
                project_id=project_id,
                task_create_or_update=task_data,  # Single object, not list
            )
            created_entries.append(created_entry)

        logger.info(
            f"Successfully created {len(created_entries)} expense entries for Project {project_id}"
        )
        return created_entries
    except Exception as e:
        logger.error(
            f"Error creating expense entries for Project {project_id}: {e}",
            exc_info=True,
        )
        raise


def update_time_entries(
    project_id: str, time_entries_data: List[Dict[str, Any]]
) -> Any:
    """
    Updates multiple time entries for a Xero Project.

    Args:
        project_id: Xero project ID
        time_entries_data: List of dictionaries containing updated time entry information

    Returns:
        Updated time entries
    """
    logger.info(
        f"Updating {len(time_entries_data)} time entries for Xero Project {project_id}"
    )

    tenant_id = get_tenant_id()
    projects_api = ProjectApi(api_client)

    try:
        # Update time entries one by one using the Projects API
        updated_entries = []
        for time_entry_data in time_entries_data:
            # Extract time_entry_id for the API call
            time_entry_id = getattr(time_entry_data, "time_entry_id", None)
            if not time_entry_id:
                raise ValueError(
                    f"time_entry_data missing time_entry_id: {time_entry_data}"
                )

            updated_entry = projects_api.update_time_entry(
                xero_tenant_id=tenant_id,
                project_id=project_id,
                time_entry_id=time_entry_id,
                time_entry_create_or_update=time_entry_data,
            )
            updated_entries.append(updated_entry)
        logger.info(
            f"Successfully updated {len(updated_entries)} time entries for Project {project_id}"
        )
        return updated_entries
    except Exception as e:
        logger.error(
            f"Error updating time entries for Project {project_id}: {e}", exc_info=True
        )
        raise


def update_expense_entries(
    project_id: str, expense_entries_data: List[Dict[str, Any]]
) -> Any:
    """
    Updates multiple expense entries for a Xero Project as tasks.

    Args:
        project_id: Xero project ID
        expense_entries_data: List of dictionaries containing updated expense entry information

    Returns:
        Updated expense entries (as tasks)
    """
    logger.info(
        f"Updating {len(expense_entries_data)} expense entries for Xero Project {project_id}"
    )

    tenant_id = get_tenant_id()
    projects_api = ProjectApi(api_client)

    try:
        # Update expense entries as tasks using the Projects API
        updated_entries = []
        for expense_entry_data in expense_entries_data:
            # Convert dict data to proper TaskCreateOrUpdate object
            rate_amount = Amount(
                currency=CurrencyCode.NZD,
                value=float(expense_entry_data["rate"]["value"]),
            )

            task_data = TaskCreateOrUpdate(
                name=expense_entry_data["name"],
                rate=rate_amount,
                charge_type=ChargeType.FIXED,
            )

            # Include task_id for updates
            if "task_id" in expense_entry_data:
                task_data.task_id = expense_entry_data["task_id"]

            updated_entry = projects_api.update_task(
                xero_tenant_id=tenant_id,
                project_id=project_id,
                task_id=expense_entry_data["task_id"],
                task_create_or_update=task_data,  # Single object, not list
            )
            updated_entries.append(updated_entry)
        logger.info(
            f"Successfully updated {len(updated_entries)} expense entries for Project {project_id}"
        )
        return updated_entries
    except Exception as e:
        logger.error(
            f"Error updating expense entries for Project {project_id}: {e}",
            exc_info=True,
        )
        raise
