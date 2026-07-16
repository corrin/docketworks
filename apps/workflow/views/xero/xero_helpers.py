# workflow/views/xero_helpers.py
import json
from datetime import date
from typing import Any, Dict, List, Optional


def sanitize_for_xero(text: str) -> str:
    """Replace angle braces with parentheses to avoid breaking Xero's XML API."""
    return text.replace("<", "(").replace(">", ")")


def clean_payload(payload):
    """Remove null fields from payload."""
    if isinstance(payload, dict):
        return {k: clean_payload(v) for k, v in payload.items() if v is not None}
    if isinstance(payload, list):
        return [clean_payload(v) for v in payload if v is not None]
    return payload


def format_date(dt: date) -> str:
    """Formats a date object to YYYY-MM-DD string."""
    if not isinstance(dt, date):
        raise TypeError(f"Expected datetime.date, got {type(dt)}")
    return dt.strftime("%Y-%m-%d")


def convert_to_pascal_case(obj):
    """
    Recursively converts dictionary keys from snake_case to PascalCase.
    Handles keys starting with an underscore.
    """

    def convert_key(key: str) -> str:
        leading_underscore = key.startswith("_")
        source = key[1:] if leading_underscore else key
        converted = "".join(
            "ID" if part == "id" else part[:1].upper() + part[1:]
            for part in source.split("_")
        )
        return f"_{converted}" if leading_underscore else converted

    if isinstance(obj, dict):
        new_dict = {}
        for key, value in obj.items():
            pascal_key = convert_key(key)
            new_dict[pascal_key] = convert_to_pascal_case(value)
        return new_dict
    elif isinstance(obj, list):
        return [convert_to_pascal_case(item) for item in obj]
    else:
        return obj


def _get_messages_from_validation_errors(
    val_errors_list: Optional[List[Dict[str, Any]]],
) -> List[str]:
    """
    Extracts 'Message' strings from a list of validation error dictionaries.
    """
    messages: List[str] = []
    if not isinstance(val_errors_list, list):
        return messages

    for error in val_errors_list:
        match error:
            case {"Message": str(msg)} if msg:
                messages.append(msg)

    return messages


def _extract_messages_from_elements(
    elements_list: Optional[List[Dict[str, Any]]],
) -> List[str]:
    """
    Extracts all relevant messages from a list of 'Elements' dictionaries.
    It prioritizes messages from 'ValidationErrors' within each element,
    then looks for a direct 'Message' key on the element itself.
    """
    all_messages: List[str] = []
    if not isinstance(elements_list, list):
        return all_messages

    for element in elements_list:
        if not isinstance(element, dict):
            continue

        validation_errors = element.get("ValidationErrors")
        extracted_val_messages = _get_messages_from_validation_errors(validation_errors)

        if extracted_val_messages:
            all_messages.extend(extracted_val_messages)
        else:
            message = element.get("Message")
            if isinstance(message, str) and message:
                all_messages.append(message)

    return all_messages


def parse_xero_api_error_message(
    exception_body: str,
    default_message: str = "An unspecified error occurred with Xero.",
) -> str:
    """
    Parses the JSON body of a Xero API exception to extract a more specific error message.

    Args:
        exception_body (str): The JSON body of the exception as a string.
        default_message (str): The message to return if parsing fails.

    Returns:
        A string containing the error message, or the default message if parsing fails.
    """
    if not exception_body:
        return default_message

    try:
        error_data = json.loads(exception_body)

        elements = error_data.get("Elements")

        # Elements first
        if isinstance(elements, list) and elements:
            processed_messages = _extract_messages_from_elements(elements)
            if processed_messages:
                return " | ".join(processed_messages)

        # Check for a top-level 'Detail', usual in 500 errors
        detail = error_data.get("Detail")
        if isinstance(detail, str) and detail:
            return detail

        # Check for a top-level 'Message' (common in validation exceptions summary)
        message = error_data.get("Message")
        if isinstance(message, str) and message:
            return message

        # Check for a top-level 'Title'
        title = error_data.get("Title")
        if isinstance(title, str) and title:
            return title

        # In case the error data is a simple string or has no structured message, we just fallback
        if isinstance(error_data, str) and error_data:
            return error_data

    except json.JSONDecodeError:
        if len(exception_body) < 250 and not exception_body.startswith("<"):
            return exception_body
    except Exception:
        pass  # Just fall through to the default message

    return default_message
