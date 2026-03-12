import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlencode

import requests
from django.conf import settings
from django.core.cache import cache
from xero_python.accounting import AccountingApi
from xero_python.api_client import ApiClient, Configuration
from xero_python.api_client.oauth2 import OAuth2Token, TokenApi
from xero_python.identity import IdentityApi
from xero_python.project import ProjectApi
from xero_python.project.models import (
    Amount,
    ChargeType,
    CurrencyCode,
    ProjectCreateOrUpdate,
    TaskCreateOrUpdate,
)

from apps.workflow.models import CompanyDefaults, XeroToken

logger = logging.getLogger("xero")

api_client = ApiClient(
    Configuration(
        debug=False,
        oauth2_token=OAuth2Token(
            client_id=settings.XERO_CLIENT_ID,
            client_secret=settings.XERO_CLIENT_SECRET,
        ),
    ),
)

token_api = TokenApi(
    api_client,
    client_id=settings.XERO_CLIENT_ID,
    client_secret=settings.XERO_CLIENT_SECRET,
)


@api_client.oauth2_token_getter
def get_token() -> Optional[Dict[str, Any]]:
    """Get token from cache or database."""
    logger.debug("Getting token from cache")
    token = cache.get("xero_token")
    if token:
        logger.debug("Retrieved token from cache")
        return token

    logger.debug("Token not found in cache, checking database")
    db_token = XeroToken.objects.first()
    if not db_token or not db_token.access_token:
        logger.debug("No valid token found in database")
        return None

    if not db_token.expires_at:
        logger.debug("Token in database has no expiry time")
        return None

    # Convert database token to OAuth2Token format
    token = {
        "access_token": db_token.access_token,
        "refresh_token": db_token.refresh_token,
        "token_type": db_token.token_type,
        "expires_at": db_token.expires_at.timestamp(),
        "scope": db_token.scope.split(),
        "expires_in": int(
            (db_token.expires_at - datetime.now(timezone.utc)).total_seconds()
        ),
    }

    # Only cache if not expired
    if token["expires_in"] > 0:
        cache.set("xero_token", token, timeout=token["expires_in"])
        logger.debug("Retrieved valid token from database and cached it")
        return token

    logger.debug("Token in database is expired")
    return None


@api_client.oauth2_token_saver
def store_token(token: Dict[str, Any]) -> None:
    """Store token in both cache and database."""
    logger.info("Storing token!")

    # For better logs if needed
    token_data = {
        "id_token": token.get("id_token"),
        "access_token": token.get("access_token"),
        "refresh_token": token.get("refresh_token"),
        "expires_in": token.get("expires_in"),
        "token_type": token.get("token_type"),
        "scope": token.get("scope", "").split(),
    }

    # Get expiry time from Xero's response
    if not token.get("expires_in"):
        logger.error("No expires_in provided in token response from Xero")
        raise ValueError("Missing expires_in in Xero token response")

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=token["expires_in"])
    token_data["expires_at"] = expires_at.timestamp()
    logger.info(f"Token will expire at {expires_at.isoformat()}")

    # Store in cache with the actual expiry time
    cache.set("xero_token", token_data, timeout=token["expires_in"])
    logger.info(f"Token stored in cache with timeout of {token['expires_in']} seconds")

    # Get tenant ID if available
    try:
        tenant_id = get_tenant_id_from_connections()
    except Exception as e:
        tenant_id = None
        logger.warning(f"Could not fetch tenant ID when storing token: {str(e)}")

    # Store in database
    try:
        xero_token = XeroToken.objects.first()
        if not xero_token:
            xero_token = XeroToken()

        # Only update refresh token if one is provided
        refresh_token = token_data.get("refresh_token")
        if refresh_token:
            xero_token.refresh_token = str(refresh_token)
            logger.info("Updated refresh token in database")

        xero_token.access_token = str(token_data["access_token"])
        xero_token.token_type = str(token_data["token_type"])
        xero_token.expires_at = expires_at
        xero_token.scope = " ".join(token_data["scope"])
        if tenant_id:
            xero_token.tenant_id = tenant_id
        xero_token.save()
        logger.info(
            f"Token stored in database with expiry at {expires_at.isoformat() if expires_at else 'None'}"
        )
    except Exception as e:
        logger.error(f"Failed to store token in database: {e}")
        # Don't raise - we still have the token in cache

    logger.debug("Token stored successfully in both cache and database.")


def refresh_token() -> Optional[Dict[str, Any]]:
    """Refresh the Xero OAuth token."""
    logger.debug("Starting token refresh")

    token = get_token()
    if not token:
        logger.debug("No token found to refresh")
        return None

    # Log the current token state
    current_expiry = datetime.fromtimestamp(token["expires_at"], tz=timezone.utc)
    current_token = token["access_token"][:10] + "..."
    logger.debug("Current token before refresh:")
    logger.debug(f"  Access token: {current_token}")
    logger.debug(f"  Expires at: {current_expiry}")

    try:
        # Create token API with proper parameters
        token_api = TokenApi(
            api_client,
            client_id=settings.XERO_CLIENT_ID,
            client_secret=settings.XERO_CLIENT_SECRET,
        )

        # Refresh the token
        refreshed_token = token_api.refresh_token(
            token["refresh_token"], token["scope"]
        )

        # Log the new token state
        new_expiry = datetime.now(timezone.utc) + timedelta(
            seconds=refreshed_token["expires_in"]
        )
        new_token_start = refreshed_token["access_token"][:10] + "..."

        logger.debug("Token refresh completed:")
        logger.debug(f"  New access token: {new_token_start}")
        logger.debug(f"  New expiry: {new_expiry}")

        # Explicitly log whether the token changed
        if current_token != new_token_start:
            logger.debug("Token was CHANGED during refresh")
        else:
            logger.debug("Token remained the SAME after refresh")

        # Save the refreshed token
        store_token(refreshed_token)

        return refreshed_token
    except Exception as e:
        logger.error(f"Token refresh failed: {str(e)}")
        raise  # Re-raise to stop execution


def get_valid_token() -> Optional[Dict[str, Any]]:
    """Get a valid token, refreshing if needed."""
    logger.debug("Getting valid token")
    token = get_token()
    if not token:
        logger.debug("No token found")
        return None

    expires_at = token.get("expires_at")
    if expires_at:
        expires_at_datetime = datetime.fromtimestamp(expires_at, tz=timezone.utc)
        # Refresh token if it expires in less than 5 minutes
        if datetime.now(timezone.utc) > expires_at_datetime - timedelta(minutes=5):
            logger.info(
                f"Xero token expiring soon at {expires_at_datetime.isoformat()}, refreshing..."
            )
            try:
                token = refresh_token()
                logger.info("Successfully refreshed Xero token")
            except Exception as e:
                logger.error(
                    f"Token refresh failed, re-authentication required: {str(e)}"
                )
                return None
    logger.debug("Returning valid token!")
    return token


def get_authentication_url(state: str) -> str:
    """Get the URL for initial Xero OAuth."""
    params = {
        "response_type": "code",
        "client_id": settings.XERO_CLIENT_ID,
        "redirect_uri": settings.XERO_REDIRECT_URI,
        "scope": " ".join(settings.XERO_SCOPES),  # actual spaces
        "state": state,
    }
    logger.info(
        f"Generating authentication URL with params: \n{json.dumps(params, indent=2, sort_keys=True)}"
    )
    # Use quote_via=quote to encode spaces as %20 instead of +
    url = f"https://login.xero.com/identity/connect/authorize?{urlencode(params, quote_via=quote)}"
    logger.info(f"Generated URL: {url}")
    return url


def get_tenant_id_from_connections() -> str:
    """Get tenant ID using current token."""
    logger.debug("Getting tenant ID from connections")
    identity_api = IdentityApi(api_client)
    connections = identity_api.get_connections()

    if not connections:
        logger.debug("No Xero tenants found")
        raise Exception("No Xero tenants found.")

    # Get company defaults
    company_defaults = CompanyDefaults.get_solo()
    if not company_defaults.xero_tenant_id:
        raise Exception(
            "No Xero tenant ID configured in company defaults. Please set this up first."
        )

    # Verify the configured tenant ID is still valid
    available_tenant_ids = [conn.tenant_id for conn in connections]
    if company_defaults.xero_tenant_id not in available_tenant_ids:
        raise Exception(
            "Configured Xero tenant ID is no longer valid. Please check your company defaults configuration."
        )

    return company_defaults.xero_tenant_id


def exchange_code_for_token(
    code: str, state: str, session_state: str
) -> Dict[str, Any]:
    """
    Exchange authorization code for access and refresh tokens from Xero.
    """
    logger.debug(
        f"Exchanging code for token. Code: {code}, State: {state}, Session State: {session_state}"
    )
    url = "https://identity.xero.com/connect/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.XERO_REDIRECT_URI,
        "client_id": settings.XERO_CLIENT_ID,
        "client_secret": settings.XERO_CLIENT_SECRET,
    }

    try:
        response = requests.post(url, headers=headers, data=data)
        response.raise_for_status()
        token = response.json()
        logger.debug("Token received!")

        store_token(token)
        logger.debug("Token stored successfully after exchange!")

        return token
    except requests.exceptions.HTTPError as e:
        logger.debug(f"HTTP Error: {response.status_code} - {response.text}")
        raise e
    except Exception as e:
        logger.debug(f"Unexpected error: {str(e)}")
        raise e


def get_tenant_id() -> str:
    """
    Retrieve the tenant ID from cache, refreshing or re-authenticating as needed.
    """
    logger.debug("Getting tenant ID")
    tenant_id = cache.get(
        "xero_tenant_id"
    )  # Step 1: Try to retrieve the tenant ID from the cache.
    logger.debug(f"Tenant ID from cache: {tenant_id}")

    token = (
        get_valid_token()
    )  # Step 2: Ensure a valid token exists, refreshing if necessary.

    if not token:
        logger.debug("No valid token found")
        raise Exception(
            "No valid Xero token found. Please complete the authorization workflow."
        )

    if (
        not tenant_id
    ):  # Step 3: If tenant ID is missing, fetch it using the current token.
        logger.debug("No tenant ID in cache, fetching from Xero")
        try:
            tenant_id = get_tenant_id_from_connections()
            logger.debug(f"Caching tenant ID: {tenant_id}")
            cache.set(
                "xero_tenant_id", tenant_id
            )  # Cache the tenant ID for future use.
        except Exception as e:
            logger.debug(f"Failed to fetch tenant ID: {str(e)}")
            raise Exception(f"Failed to fetch tenant ID: {str(e)}")

    logger.debug(f"Returning tenant ID: {tenant_id}")
    return tenant_id


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
