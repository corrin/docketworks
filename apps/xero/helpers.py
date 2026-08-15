"""Payload and error-message helpers for the Xero document push.

``clean_payload`` + ``convert_to_pascal_case`` exist because the SDK's own
serializer is not used on the create path: documents are posted as raw dicts
(``invoices={"Invoices": [...]}``) so that None-valued fields can be stripped —
the SDK serializer sends them, and Xero rejects explicit nulls on some fields.
"""

import json
from datetime import date, datetime
from typing import Any


def as_date(value: Any) -> date | None:
    """Narrow a Xero date-or-datetime field to a plain date.

    The SDK returns datetimes for some date fields and dates for others
    depending on the endpoint, so every payroll comparison has to normalise
    before it can compare.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"Expected a Xero date or datetime, got {type(value).__name__}: {value!r}")


def sanitize_for_xero(text: str) -> str:
    """Replace angle brackets with parentheses to avoid breaking Xero's XML API."""
    return text.replace("<", "(").replace(">", ")")


def clean_payload(payload: Any) -> Any:
    """Recursively remove None-valued fields from a payload."""
    if isinstance(payload, dict):
        return {key: clean_payload(value) for key, value in payload.items() if value is not None}
    if isinstance(payload, list):
        return [clean_payload(value) for value in payload if value is not None]
    return payload


def _convert_key(key: str) -> str:
    """snake_case → PascalCase, ``id`` → ``ID``, leading underscore preserved."""
    leading_underscore = key.startswith("_")
    source = key[1:] if leading_underscore else key
    converted = "".join(
        "ID" if part == "id" else part[:1].upper() + part[1:] for part in source.split("_")
    )
    return f"_{converted}" if leading_underscore else converted


def convert_to_pascal_case(obj: Any) -> Any:
    """Recursively convert dictionary keys from snake_case to PascalCase."""
    if isinstance(obj, dict):
        return {_convert_key(key): convert_to_pascal_case(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [convert_to_pascal_case(item) for item in obj]
    return obj


def _messages_from_validation_errors(validation_errors: object) -> list[str]:
    """Extract 'Message' strings from a list of validation error dictionaries."""
    if not isinstance(validation_errors, list):
        return []
    messages: list[str] = []
    for error in validation_errors:
        match error:
            case {"Message": str(msg)} if msg:
                messages.append(msg)
    return messages


def _messages_from_elements(elements: list[Any]) -> list[str]:
    """Extract messages from 'Elements' entries.

    ValidationErrors within an element win over the element's own 'Message':
    they carry the per-field detail; the element message is a summary.
    """
    all_messages: list[str] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        validation_messages = _messages_from_validation_errors(element.get("ValidationErrors"))
        if validation_messages:
            all_messages.extend(validation_messages)
        else:
            message = element.get("Message")
            if isinstance(message, str) and message:
                all_messages.append(message)
    return all_messages


def parse_xero_api_error_message(  # noqa: PLR0911 -- each return is one rung of the documented precedence ladder
    exception_body: str | bytes | None,
    default_message: str = "An unspecified error occurred with Xero.",
) -> str:
    """Extract the most specific human-readable message from a Xero error body.

    Precedence: Elements' ValidationErrors → top-level Detail (500s) →
    Message (validation summaries) → Title → the raw body when it is short
    plain text → ``default_message``.
    """
    if not exception_body:
        return default_message
    body = (
        exception_body.decode("utf-8", errors="replace")
        if isinstance(exception_body, bytes)
        else exception_body
    )

    try:
        error_data = json.loads(body)
    # deliberate-swallow: a non-JSON body is an expected Xero failure shape
    # (HTML error pages, plain-text proxies); short plain text is itself the
    # best available message
    except json.JSONDecodeError:
        if len(body) < 250 and not body.startswith("<"):
            return body
        return default_message

    if isinstance(error_data, str):
        return error_data or default_message
    if not isinstance(error_data, dict):
        return default_message

    elements = error_data.get("Elements")
    if isinstance(elements, list) and elements:
        element_messages = _messages_from_elements(elements)
        if element_messages:
            return " | ".join(element_messages)

    for key in ("Detail", "Message", "Title"):
        value = error_data.get(key)
        if isinstance(value, str) and value:
            return value

    return default_message
