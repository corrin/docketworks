#!/usr/bin/env python
"""
Test script for KPI Service functionality

This script allows direct testing of the KPI calendar service without
needing to run the full web server. Useful for debugging KPI calculation issues.

Usage:
    python scripts/test_kpi_service.py [year] [month]

Examples:
    python scripts/test_kpi_service.py  # Tests current month
    python scripts/test_kpi_service.py 2025 6  # Tests June 2025
"""

import logging
import os
import sys
import traceback
from datetime import date

import django

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")
django.setup()

from apps.accounting.services import KPIService


def test_kpi_calendar(year=None, month=None):
    """Test the KPI calendar service directly"""
    if year is None:
        year = date.today().year
    if month is None:
        month = date.today().month

    try:
        logger.info(f"Testing KPI calendar for {year}-{month:02d}...")
        result = KPIService.get_calendar_data(year, month)

        calendar_data = result.get("calendar_data", {})
        monthly_totals = result.get("monthly_totals", {})

        logger.info(f"Success! Got {len(calendar_data)} days of data")
        logger.info("")
        logger.info("Monthly summary:")
        logger.info(f"  - Working days: {monthly_totals.get('working_days', 0)}")
        logger.info(
            f"  - Billable hours: {monthly_totals.get('billable_hours', 0):.1f}"
        )
        logger.info(f"  - Total hours: {monthly_totals.get('total_hours', 0):.1f}")
        logger.info(f"  - Gross profit: ${monthly_totals.get('gross_profit', 0):.2f}")

        return True
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        logger.error("")
        logger.error("Full traceback:")
        logger.error(traceback.format_exc())
        return False


if __name__ == "__main__":
    # Parse command line arguments
    args = sys.argv[1:]
    year = int(args[0]) if len(args) > 0 else None
    month = int(args[1]) if len(args) > 1 else None

    success = test_kpi_calendar(year, month)
    sys.exit(0 if success else 1)
