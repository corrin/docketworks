import logging
import uuid
from typing import Any, Dict, List, Optional

from django.contrib.messages import get_messages
from django.http import HttpRequest

logger = logging.getLogger(__name__)


def extract_messages(request: HttpRequest) -> List[Dict[str, Any]]:
    """
    Extracts messages from the request object and returns them as a list of
    dictionaries.
    Each dictionary contains the message level tag and the message text.

    Args:
        request: The HTTP request object containing the messages

    Returns:
        list: A list of dictionaries, where each dictionary has:
            - level (str): The message level tag (e.g. 'info', 'error')
            - message (str): The message text
    """

    return [
        {"level": message.level_tag, "message": message.message}
        for message in get_messages(request)
    ]


def is_valid_uuid(value: str) -> bool:
    """Check if the given string is a valid UUID."""
    try:
        uuid.UUID(value)
        return True
    except (ValueError, TypeError):
        return False


def is_valid_invoice_number(value: str) -> bool:
    """
    Check if the given string is a valid invoice number.
    """
    if "INV-" in value:
        parts = value.split("-")
        if len(parts) == 2 and parts[1].isdigit():
            return True
    return False


def get_machine_id(path: str = "/etc/machine-id") -> Optional[str]:
    """
    Reads the machine ID from the specified path.
    Defaults to /etc/machine-id for Linux systems.
    """
    try:
        with open(path) as f:
            return f.read().strip()
    except FileNotFoundError:
        logger.warning(
            f"Machine ID file not found at {path}. Cannot determine production environment based on machine ID."
        )
        return None
    except Exception as e:
        logger.error(f"Error reading machine ID file {path}: {e}")
        return None


def parse_pagination_params(request) -> tuple[int, int]:
    """
    Parse and validate pagination parameters from request.

    Args:
        request: HTTP request object with query_params

    Returns:
        tuple[int, int]: (limit, offset) with defaults and validation

    Raises:
        ValueError: If parameters are invalid
    """
    try:
        limit = int(request.query_params.get("limit", "50"))
        offset = int(request.query_params.get("offset", "0"))
    except (TypeError, ValueError):
        raise ValueError("Invalid pagination parameters")
    return limit, offset


def build_xero_payroll_url(pay_run_xero_id: str) -> Optional[str]:
    """
    Build a Xero Payroll deep link URL for a pay run.

    Args:
        pay_run_xero_id: The Xero UUID of the pay run

    Returns:
        The deep link URL, or None if xero_shortcode is not configured

    Raises:
        ValueError: If xero_shortcode is not configured
    """
    from apps.workflow.models import CompanyDefaults

    company = CompanyDefaults.get_solo()
    shortcode = company.xero_shortcode

    if not shortcode:
        raise ValueError(
            "Xero shortcode not configured. "
            "Run 'python manage.py xero --setup' to fetch it."
        )

    return (
        f"https://payroll.xero.com/PayRun"
        f"?CID={shortcode}"
        f"#payruns/{pay_run_xero_id}"
    )
