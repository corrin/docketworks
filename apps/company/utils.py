"""
Company utility functions
"""

from datetime import datetime, time

from django.utils import timezone


def date_to_datetime(date_obj):
    """
    Convert a date object to a timezone-aware datetime at midnight.
    Returns None if date_obj is None.

    Args:
        date_obj: A date object or None

    Returns:
        A timezone-aware datetime at midnight, or None
    """
    if date_obj is None:
        return None
    return datetime.combine(date_obj, time.min, tzinfo=timezone.get_current_timezone())
