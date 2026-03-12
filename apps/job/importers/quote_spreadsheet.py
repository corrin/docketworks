# flake8: noqa
# pylint: skip-file
# This entire file is AI slop and will be rewritten - no point fixing linting issues

import logging
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

import pandas as pd

from .draft import DraftLine

logger = logging.getLogger(__name__)

# WARNING, WARNING, WARNING: This code is absolutely full of AI slop
# It is slated to be deleted and totally rewritten
# DO NOT TRUST A SINGLE THING IT SAYS - IT IS IN DIRECT CONTRADICTION TO THE REQUIREMENTS


class ErrorSeverity(Enum):
    """Severity levels for validation errors."""

    WARNING = "warning"  # Non-blocking, proceed with import
    ERROR = "error"  # Blocking, reject import
    CRITICAL = "critical"  # Critical format issues, cannot parse


class ErrorType(Enum):
    """Types of validation errors."""

    # Format errors (critical)
    MISSING_REQUIRED_COLUMNS = "missing_required_columns"
    INVALID_SHEET_STRUCTURE = "invalid_sheet_structure"

    # Data conflicts (errors - blocking)
    LABOUR_MATERIAL_CONFLICT = "labour_material_conflict"
    INVALID_ITEM_FORMAT = "invalid_item_format"
    PRICING_MISMATCH = "pricing_mismatch"

    # Validation warnings (non-blocking)
    MARKUP_MISMATCH = "markup_mismatch"
    CHARGE_RATE_MISMATCH = "charge_rate_mismatch"
    TOTALS_MISMATCH = "totals_mismatch"


@dataclass
class ValidationError:
    """Individual validation error with context."""

    error_type: ErrorType
    severity: ErrorSeverity
    message: str
    row_number: Optional[int] = None
    column: Optional[str] = None
    expected_value: Optional[Any] = None
    actual_value: Optional[Any] = None
    suggestion: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert ValidationError to dictionary for JSON serialization."""
        return {
            "error_type": self.error_type.value if self.error_type else None,
            "severity": self.severity.value if self.severity else None,
            "message": self.message,
            "row_number": self.row_number,
            "column": self.column,
            "expected_value": self.expected_value,
            "actual_value": self.actual_value,
            "suggestion": self.suggestion,
        }


@dataclass
class ValidationReport:
    """Complete validation report for a spreadsheet."""

    is_valid: bool
    can_proceed: bool  # True if only warnings, False if errors/critical
    errors: List[ValidationError]
    warnings: List[ValidationError]
    critical_issues: List[ValidationError]
    summary: Dict[str, Any]

    def has_blocking_issues(self) -> bool:
        """Check if there are any blocking issues (errors or critical)."""
        return len(self.errors) > 0 or len(self.critical_issues) > 0

    def get_error_summary(self) -> str:
        """Get a human-readable summary of all issues."""
        if not self.errors and not self.warnings and not self.critical_issues:
            return "✅ No validation issues found"

        summary_parts = []
        if self.critical_issues:
            summary_parts.append(f"🚨 {len(self.critical_issues)} critical issue(s)")
        if self.errors:
            summary_parts.append(f"❌ {len(self.errors)} error(s)")
        if self.warnings:
            summary_parts.append(f"⚠️ {len(self.warnings)} warning(s)")

        return " | ".join(summary_parts)

    def to_dict(self) -> Dict[str, Any]:
        """Convert ValidationReport to dictionary for JSON serialization."""
        # Combine all issues into a single list with consistent format
        all_issues = []

        # Add critical issues
        for issue in self.critical_issues:
            issue_dict = issue.to_dict()
            issue_dict["severity"] = "error"  # Treat critical as error for frontend
            all_issues.append(issue_dict)

        # Add errors
        for issue in self.errors:
            all_issues.append(issue.to_dict())

        # Add warnings
        for issue in self.warnings:
            all_issues.append(issue.to_dict())

        return {
            "is_valid": self.is_valid,
            "can_proceed": self.can_proceed,
            "issues": all_issues,
            "errors": [issue.message for issue in self.errors],
            "warnings": [issue.message for issue in self.warnings],
            "summary": self.summary,
        }


def _d(val):
    """Safely coerce values to Decimal with 2 decimal places precision."""
    try:
        # Handle pandas NaN, None, empty strings
        if pd.isna(val) or val is None or val == "":
            return Decimal("0")

        # Convert to string and clean common issues
        str_val = str(val).strip()
        if str_val.lower() in ["nan", "none", "", "#n/a"]:
            return Decimal("0")

        # Remove any currency symbols or commas
        str_val = str_val.replace("$", "").replace(",", "").replace(" ", "")

        return Decimal(str_val).quantize(Decimal("0.01"))
    except (ValueError, TypeError, Exception):
        return Decimal("0")


PRIMARY_SHEET = "Primary Details"

# Support both workbook layouts
LABOUR_COLS = ["Labour /laser (inhouse)", "assembly"]  # older and newer files
MATERIAL_TOTAL_COL = "total cost"  # column N (but may have trailing space)
MATERIAL_ITEM_COL = "item cost"  # column O
QUANTITY_COL = "quantity"  # column B

# Default values if CompanyDefaults not available
DEFAULT_WAGE_RATE = Decimal("32.00")
DEFAULT_CHARGE_OUT_RATE = Decimal("110.00")
DEFAULT_MATERIALS_MARKUP = Decimal("0.20")  # 20%

# Columns to ignore for DraftLine creation
IGNORE_COLS = [
    "total cost",
    "item cost",
    "Labour hours cost",
    "Cost before MU",
    "Total cost + MU",
]


def detect_labour_column(df):
    """Detect which labour column is present in this workbook."""
    for col in LABOUR_COLS:
        if col in df.columns:
            return col
    # If no labour column found, we'll just process materials
    return None


def detect_material_columns(df):
    """Detect material cost columns, handling trailing spaces."""
    total_col = None
    item_col = None

    # Look for total cost column (may have trailing space)
    for col in df.columns:
        if col.strip().lower() == "total cost":
            total_col = col
            break

    # Look for item cost column
    for col in df.columns:
        if col.strip().lower() == "item cost":
            item_col = col
            break

    return total_col, item_col


def parse_xlsx(
    path: str, company=None, skip_validation=False
) -> tuple[list[DraftLine], list[str]]:
    """
    Parse the Quoting Spreadsheet and convert Primary Details sheet
    into a list of DraftLine objects with validation.

    Args:
        path: Path to the Excel file
        company: Company object with wage_rate and charge_out_rate (optional)
        skip_validation: Skip pre-import validation (default: False)

    Returns:
        tuple: (draft_lines, validation_report)
    """
    try:
        # Perform pre-import validation
        if not skip_validation:
            validation_report = validate_spreadsheet_format(path)

            # Reject if critical issues or blocking errors
            if validation_report.has_blocking_issues():
                error_summary = []

                # Add critical issues
                for issue in validation_report.critical_issues:
                    error_summary.append(f"CRITICAL: {issue.message}")

                # Add blocking errors
                for issue in validation_report.errors:
                    error_summary.append(f"ERROR: {issue.message}")
                    if issue.row_number:
                        error_summary[-1] += f" (Row {issue.row_number})"
                    if issue.suggestion:
                        error_summary[-1] += f" - {issue.suggestion}"

                # Return empty results with detailed error report
                return [], error_summary
        # Read the Primary Details sheet
        logger.info(f"🔍 Reading Primary Details sheet from: {path}")
        df = pd.read_excel(path, sheet_name=PRIMARY_SHEET)
        logger.info(f"📊 Loaded DataFrame with shape: {df.shape}")
        logger.info(f"📋 DataFrame columns: {list(df.columns)}")

        # Log sample of raw data
        logger.info("📝 Sample raw data (first 3 rows):")
        for i in range(min(3, len(df))):
            row_data = df.iloc[i].to_dict()
            logger.info(f"    Row {i}: {row_data}")

        # Read pricing details for validation
        pricing_df = None
        try:
            pricing_df = pd.read_excel(path, sheet_name="pricing details - inhouse")
            logger.info("📊 Also loaded pricing details sheet")
        except Exception:
            logger.info("📊 No pricing details sheet found (optional)")
            pass  # Optional sheet for validation

        # Detect columns
        labour_col = detect_labour_column(df)
        material_total_col, material_item_col = detect_material_columns(
            df
        )  # Get company rates from CompanyDefaults if available
        if company:
            wage_rate = getattr(company, "wage_rate", DEFAULT_WAGE_RATE)
            charge_out_rate = getattr(
                company, "charge_out_rate", DEFAULT_CHARGE_OUT_RATE
            )
            materials_markup = getattr(
                company, "materials_markup", DEFAULT_MATERIALS_MARKUP
            )
        else:
            # Try to get from CompanyDefaults model
            try:
                from apps.workflow.models import CompanyDefaults

                defaults = CompanyDefaults.get_solo()
                if defaults:
                    wage_rate = defaults.wage_rate
                    charge_out_rate = defaults.charge_out_rate
                    materials_markup = defaults.materials_markup
                else:
                    wage_rate = DEFAULT_WAGE_RATE
                    charge_out_rate = DEFAULT_CHARGE_OUT_RATE
                    materials_markup = DEFAULT_MATERIALS_MARKUP
            except (ImportError, Exception):
                wage_rate = DEFAULT_WAGE_RATE
                charge_out_rate = DEFAULT_CHARGE_OUT_RATE
                materials_markup = DEFAULT_MATERIALS_MARKUP

        draft_lines = []
        total_minutes = Decimal("0")
        valid_items_count = 0
        skipped_items_count = 0

        logger.info("🔧 Starting to process rows (max 45 rows)...")
        # Process rows - only those with valid item numbers in column A or valid
        # quantity
        auto_item_number = 1  # Counter for auto-assigned item numbers

        for idx in range(0, min(45, len(df))):
            row = df.iloc[idx]
            excel_row = idx + 1  # Convert to Excel row number

            logger.debug(f"Processing row {excel_row}: {row.to_dict()}")

            # Check 1: Quantity first (must have value and not be zero)
            quantity = _d(row.get(QUANTITY_COL, 1))
            if quantity <= 0:
                logger.debug(
                    f"    ⏭️ Row {excel_row}: Invalid quantity {quantity}, skipping"
                )
                skipped_items_count += 1
                continue

            # Check 2: Item number - auto-assign if missing or invalid
            item_number = str(row.get("item", "")).strip()
            if not item_number or item_number.lower() in ["nan", "none", ""]:
                # Auto-assign sequential item number
                item_number = str(auto_item_number)
                logger.info(
                    f"    🔄 Row {excel_row}: No item number, "
                    f"auto-assigned: {item_number}"
                )
                auto_item_number += 1
            else:
                try:
                    float(item_number)  # Accept floats like 1.0, 2.0
                    auto_item_number = max(
                        auto_item_number, int(float(item_number)) + 1
                    )  # Update counter
                except (ValueError, TypeError):
                    # Invalid item number, auto-assign
                    item_number = str(auto_item_number)
                    logger.info(
                        f"    🔄 Row {excel_row}: Invalid item number, "
                        f"auto-assigned: {item_number}"
                    )
                    auto_item_number += 1

            # Check 3: Description (if empty, use item number as fallback)
            description = str(row.get("Description", "")).strip()
            if not description or description.lower() in ["nan", "none", ""]:
                description = (
                    f"Item {item_number}"  # Use item number as description if blank
                )

            logger.info(
                f"    ✅ Row {excel_row}: Valid item - {item_number}, qty: {quantity}, desc: '{description}'"
            )
            valid_items_count += 1
            # Get values from key columns only (A, B, C, D, N, O)
            minutes = _d(row.get(labour_col, 0)) if labour_col else Decimal("0")
            material_total_cost = (
                _d(row.get(material_total_col, 0))
                if material_total_col
                else Decimal("0")
            )
            material_item_cost = (
                _d(row.get(material_item_col, 0)) if material_item_col else Decimal("0")
            )  # Business logic: 1 DraftLine per item
            # IF labour exists → kind='time'
            # ELSE IF item cost exists → kind='material'
            # VALIDATION: Cannot have both labour AND material
            has_labour = minutes > 0
            has_material = material_total_cost > 0 or material_item_cost > 0

            # Validation check: item cannot have both labour and material
            if has_labour and has_material:
                error_msg = (
                    f"Row {excel_row} has both labour ({minutes} min) and material costs "
                    f"(${material_total_cost}/${material_item_cost}). Invalid data."
                )
                logger.error(error_msg)
                return [], [error_msg]

            if has_labour:
                # Create time entry (labour minutes → hours)
                hours = (minutes / Decimal("60")).quantize(Decimal("0.01"))
                total_minutes += minutes

                draft_lines.append(
                    DraftLine(
                        kind="time",
                        desc=f"{description} - Labour",
                        quantity=hours,
                        unit_cost=wage_rate,
                        unit_rev=charge_out_rate,
                        source_row=excel_row,
                        source_sheet=PRIMARY_SHEET,
                    )
                )

            elif has_material:
                # Create material entry
                # unit_cost comes from column O ("item cost")
                # unit_rev = unit_cost * (1 + materials_markup)
                unit_cost = material_item_cost
                unit_rev = unit_cost * (1 + materials_markup)

                draft_lines.append(
                    DraftLine(
                        kind="material",
                        desc=f"{description} - Materials",
                        quantity=quantity,
                        unit_cost=unit_cost,
                        unit_rev=unit_rev,
                        source_row=excel_row,
                        source_sheet=PRIMARY_SHEET,
                    )
                )

            # If neither labour nor material, skip this item        # Validation - collect totals from summary rows
        validation_report = validate_totals(
            df, draft_lines, total_minutes, labour_col, materials_markup, pricing_df
        )

        logger.info("✅ Parsing completed!")
        logger.info("📊 Final statistics:")
        logger.info(f"    Valid items processed: {valid_items_count}")
        logger.info(f"    Items skipped: {skipped_items_count}")
        logger.info(f"    Draft lines created: {len(draft_lines)}")
        logger.info(f"    Total minutes: {total_minutes}")

        # Log sample of created draft lines
        logger.info("📝 Sample draft lines created:")
        for i, line in enumerate(draft_lines[:3]):
            logger.info(f"    Line {i}: {line}")

        return draft_lines, validation_report

    except FileNotFoundError:
        raise FileNotFoundError(f"Excel file not found: {path}")
    except Exception as e:
        raise Exception(f"Error parsing Excel file: {str(e)}")


def find_validation_cells(df, labour_col):
    """
    Find validation cells dynamically based on content, not fixed positions.

    Returns:
        dict: Contains validation values found in the spreadsheet
    """
    validation_data = {
        "total_minutes": Decimal("0"),
        "labour_revenue": Decimal("0"),
        "material_cost_before_mu": Decimal("0"),
        "material_cost_with_mu": Decimal("0"),
        "final_cost": Decimal("0"),
    }

    try:
        # Search through the dataframe for specific text patterns
        for idx in range(len(df)):
            row = df.iloc[idx]

            # Check Description column for key markers
            description = str(row.get("Description", "")).strip().lower()

            if "labour hours cost" in description:
                # Labour revenue is to the right (in labour column)
                validation_data["labour_revenue"] = _d(row.get(labour_col, 0))

            elif "cost before mu" in description:
                # Material cost before markup is to the right (in labour column)
                validation_data["material_cost_before_mu"] = _d(row.get(labour_col, 0))

            elif "total cost + mu" in description or (
                "total cost" in description and "mu" in description
            ):
                # Material cost with markup is to the right (in labour column)
                validation_data["material_cost_with_mu"] = _d(row.get(labour_col, 0))

            elif "final cost" in description:
                # Final cost is to the right (in labour column)
                validation_data["final_cost"] = _d(row.get(labour_col, 0))
        # Find total minutes: last non-zero value in labour column before "Labour hours cost" line
        if labour_col:
            labour_hours_cost_idx = None

            # First, find the "Labour hours cost" line
            for idx in range(len(df)):
                row = df.iloc[idx]
                description = str(row.get("Description", "")).strip().lower()
                if "labour hours cost" in description:
                    labour_hours_cost_idx = idx
                    break

            # Then search backwards from that line to find the last minutes value
            if labour_hours_cost_idx is not None:
                for idx in range(labour_hours_cost_idx - 1, -1, -1):
                    row = df.iloc[idx]
                    minutes_val = _d(row.get(labour_col, 0))
                    if minutes_val > 0:
                        validation_data["total_minutes"] = minutes_val
                        break

    except Exception as e:
        logger.warning(f"Could not find all validation cells: {e}")

    return validation_data


def validate_totals(
    df,
    lines,
    total_minutes,
    labour_col,
    materials_markup=DEFAULT_MATERIALS_MARKUP,
    pricing_df=None,
):
    """
    Validate our computed totals against spreadsheet summary rows using dynamic content-based search.

    Returns:
        list[str]: Validation issues found
    """
    issues = []

    try:
        # Validate pricing details if available
        if pricing_df is not None and len(pricing_df) > 1:
            # Get labour cost and margin from pricing details (row 1)
            spreadsheet_labour_cost = _d(pricing_df.iloc[1].get("labour cost", 0))
            spreadsheet_margin = _d(pricing_df.iloc[1].get("margin", 1.2))

            # Get our company defaults for comparison
            from apps.workflow.models import CompanyDefaults

            try:
                defaults = CompanyDefaults.get_solo()
                if defaults:
                    our_charge_out_rate = defaults.charge_out_rate
                    our_materials_markup = defaults.materials_markup

                    # Validate labour cost (should match charge_out_rate)
                    labour_diff = abs(spreadsheet_labour_cost - our_charge_out_rate)
                    if labour_diff > Decimal("0.01"):
                        issues.append(
                            f"Labour cost mismatch: spreadsheet ${spreadsheet_labour_cost}, system ${our_charge_out_rate}"
                        )

                    # Validate margin (1.2 = 20% markup)
                    spreadsheet_markup = (
                        spreadsheet_margin - 1
                        if spreadsheet_margin > 1
                        else Decimal("0")
                    )
                    markup_diff = abs(spreadsheet_markup - our_materials_markup)
                    if markup_diff > Decimal("0.01"):
                        issues.append(
                            f"Material markup mismatch: spreadsheet {spreadsheet_markup:.1%}, "
                            f"system {our_materials_markup:.1%}"
                        )
            except Exception:
                pass  # Skip validation if can't access CompanyDefaults

        # Find validation cells dynamically based on content
        validation_data = find_validation_cells(df, labour_col)
        # Compute our totals
        our_minutes = sum(line.quantity * 60 for line in lines if line.kind == "time")
        our_labour_rev = sum(
            line.quantity * line.unit_rev for line in lines if line.kind == "time"
        )
        our_material_cost = sum(
            line.quantity * line.unit_cost for line in lines if line.kind == "material"
        )
        our_material_cost_mu = our_material_cost * (1 + materials_markup)
        our_final_cost = our_labour_rev + our_material_cost_mu
        # Check for mismatches using dynamic validation data
        if abs(our_minutes - validation_data["total_minutes"]) > Decimal("0.1"):
            issues.append(
                f"Minutes mismatch: computed {our_minutes}, spreadsheet {validation_data['total_minutes']}"
            )

        if abs(our_labour_rev - validation_data["labour_revenue"]) > Decimal("1.00"):
            issues.append(
                f"Labour revenue mismatch: computed ${our_labour_rev}, spreadsheet ${validation_data['labour_revenue']}"
            )

        if abs(
            our_material_cost - validation_data["material_cost_before_mu"]
        ) > Decimal("1.00"):
            issues.append(
                f"Material cost mismatch: computed ${our_material_cost}, spreadsheet ${validation_data['material_cost_before_mu']}"
            )

        if abs(
            our_material_cost_mu - validation_data["material_cost_with_mu"]
        ) > Decimal("1.00"):
            # Check if markup percentage is different
            if validation_data["material_cost_before_mu"] > 0:  # avoid division by zero
                spreadsheet_markup = (
                    validation_data["material_cost_with_mu"]
                    - validation_data["material_cost_before_mu"]
                ) / validation_data["material_cost_before_mu"]
                markup_diff = abs(spreadsheet_markup - materials_markup)
                if markup_diff > Decimal("0.01"):  # 1% tolerance
                    issues.append(
                        f"Spreadsheet uses {spreadsheet_markup:.1%} markup, system uses {materials_markup:.1%}. Adjust markup or accept?"
                    )
                else:
                    issues.append(
                        f"Material + MU mismatch: computed ${our_material_cost_mu}, spreadsheet ${validation_data['material_cost_with_mu']}"
                    )

        if abs(our_final_cost - validation_data["final_cost"]) > Decimal("1.00"):
            issues.append(
                f"Final cost mismatch: computed ${our_final_cost}, spreadsheet ${validation_data['final_cost']}"
            )

    except (IndexError, KeyError) as e:
        issues.append(f"Could not read validation cells: {e}")

    return issues


# Backward compatibility wrapper
def parse_xlsx_old(path: str) -> list[DraftLine]:
    """Backward compatibility wrapper - returns only draft_lines."""
    draft_lines, _ = parse_xlsx(path)
    return draft_lines


def parse_xlsx_with_summary(path: str) -> dict:
    """
    Parse the Excel file and return both draft lines and summary statistics.

    Args:
        path: Path to the Excel file

    Returns:
        Dictionary containing 'draft_lines', 'summary', and 'validation_report'
    """
    draft_lines, validation_report = parse_xlsx(path)

    summary = {
        "total_lines": len(draft_lines),
        "time_lines": len([line for line in draft_lines if line.kind == "time"]),
        "material_lines": len(
            [line for line in draft_lines if line.kind == "material"]
        ),
        "adjust_lines": len([line for line in draft_lines if line.kind == "adjust"]),
        "total_cost": sum(line.total_cost for line in draft_lines),
        "total_revenue": sum(line.total_rev for line in draft_lines),
    }

    return {
        "draft_lines": draft_lines,
        "summary": summary,
        "validation_report": validation_report,
    }


def parse_xlsx_with_validation(path: str, company=None) -> dict:
    """
    Parse Excel file with comprehensive validation and error reporting.

    Args:
        path: Path to the Excel file
        company: Company object with wage_rate and charge_out_rate (optional)

    Returns:
        Dictionary containing:
        - 'success': bool - Whether parsing was successful
        - 'can_proceed': bool - Whether import can proceed (no blocking errors)
        - 'draft_lines': list - Parsed DraftLine objects (empty if failed)
        - 'validation_report': ValidationReport - Complete validation results
        - 'summary': dict - Summary statistics
        - 'error_report': list - Human-readable error messages
    """
    try:
        # Always perform validation first
        validation_report = validate_spreadsheet_format(path)

        # Prepare result structure
        result = {
            "success": False,
            "can_proceed": validation_report.can_proceed,
            "draft_lines": [],
            "validation_report": validation_report,
            "summary": validation_report.summary,
            "error_report": [],
        }

        # Generate human-readable error report
        error_report = []

        # Add critical issues
        if validation_report.critical_issues:
            error_report.append("🚨 CRITICAL ISSUES (Cannot proceed):")
            for issue in validation_report.critical_issues:
                error_report.append(f"  • {issue.message}")
                if issue.suggestion:
                    error_report.append(f"    💡 {issue.suggestion}")

        # Add blocking errors
        if validation_report.errors:
            error_report.append("❌ BLOCKING ERRORS (Must fix before import):")
            for issue in validation_report.errors:
                msg = f"  • {issue.message}"
                if issue.row_number:
                    msg += f" (Row {issue.row_number})"
                error_report.append(msg)
                if issue.suggestion:
                    error_report.append(f"    💡 {issue.suggestion}")

        # Add warnings
        if validation_report.warnings:
            error_report.append("⚠️ WARNINGS (Non-blocking, import can proceed):")
            for issue in validation_report.warnings:
                msg = f"  • {issue.message}"
                if issue.expected_value and issue.actual_value:
                    msg += f" (Expected: {issue.expected_value}, Got: {issue.actual_value})"
                error_report.append(msg)
                if issue.suggestion:
                    error_report.append(f"    💡 {issue.suggestion}")

        result["error_report"] = error_report

        # If there are blocking issues, don't attempt parsing
        if validation_report.has_blocking_issues():
            result["summary"]["parse_attempted"] = False
            result["summary"]["rejection_reason"] = "Blocking validation errors found"
            return result

        # Attempt parsing (skip validation since we already did it)
        draft_lines, legacy_validation_issues = parse_xlsx(
            path, company, skip_validation=True
        )

        # Update result with successful parsing
        result["success"] = True
        result["draft_lines"] = draft_lines
        result["summary"].update(
            {
                "parse_attempted": True,
                "total_lines": len(draft_lines),
                "time_lines": len(
                    [line for line in draft_lines if line.kind == "time"]
                ),
                "material_lines": len(
                    [line for line in draft_lines if line.kind == "material"]
                ),
                "adjust_lines": len(
                    [line for line in draft_lines if line.kind == "adjust"]
                ),
                "total_cost": sum(line.total_cost for line in draft_lines),
                "total_revenue": sum(line.total_rev for line in draft_lines),
            }
        )

        # Add any legacy validation issues as warnings
        if legacy_validation_issues:
            if (
                not error_report
                or error_report[-1] != "⚠️ WARNINGS (Non-blocking, import can proceed):"
            ):
                error_report.append("⚠️ ADDITIONAL VALIDATION NOTES:")
            for issue in legacy_validation_issues:
                error_report.append(f"  • {issue}")
            result["error_report"] = error_report

        return result

    except Exception as e:
        # Unexpected error during validation or parsing
        return {
            "success": False,
            "can_proceed": False,
            "draft_lines": [],
            "validation_report": ValidationReport(
                is_valid=False,
                can_proceed=False,
                errors=[],
                warnings=[],
                critical_issues=[
                    ValidationError(
                        error_type=ErrorType.INVALID_SHEET_STRUCTURE,
                        severity=ErrorSeverity.CRITICAL,
                        message=f"Unexpected error: {str(e)}",
                    )
                ],
                summary={
                    "total_issues": 1,
                    "critical_count": 1,
                    "error_count": 0,
                    "warning_count": 0,
                },
            ),
            "summary": {"total_issues": 1, "parse_attempted": False},
            "error_report": [f"🚨 CRITICAL ERROR: {str(e)}"],
        }


# ...existing code...
def validate_spreadsheet_format(path: str) -> ValidationReport:
    """
    Perform comprehensive pre-import validation of the spreadsheet.

    Args:
        path: Path to the Excel file

    Returns:
        ValidationReport: Complete validation report with errors and warnings
    """
    errors = []
    warnings = []
    critical_issues = []

    try:
        # Check if file exists and is readable
        try:
            df = pd.read_excel(path, sheet_name=PRIMARY_SHEET)
        except FileNotFoundError:
            critical_issues.append(
                ValidationError(
                    error_type=ErrorType.INVALID_SHEET_STRUCTURE,
                    severity=ErrorSeverity.CRITICAL,
                    message=f"File not found: {path}",
                )
            )
            return _create_validation_report(critical_issues, errors, warnings, df=None)
        except Exception as e:
            critical_issues.append(
                ValidationError(
                    error_type=ErrorType.INVALID_SHEET_STRUCTURE,
                    severity=ErrorSeverity.CRITICAL,
                    message=f"Cannot read Primary Details sheet: {str(e)}",
                )
            )
            return _create_validation_report(critical_issues, errors, warnings, df=None)

        # Check required columns
        required_columns = ["item", "quantity", "Description"]
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            critical_issues.append(
                ValidationError(
                    error_type=ErrorType.MISSING_REQUIRED_COLUMNS,
                    severity=ErrorSeverity.CRITICAL,
                    message=f"Missing required columns: {', '.join(missing_columns)}",
                    suggestion="Ensure spreadsheet has 'item', 'quantity', and 'Description' columns",
                )
            )

        # Check for labour or material columns
        labour_col = detect_labour_column(df)
        material_total_col, material_item_col = detect_material_columns(df)

        if not labour_col and not material_total_col and not material_item_col:
            critical_issues.append(
                ValidationError(
                    error_type=ErrorType.MISSING_REQUIRED_COLUMNS,
                    severity=ErrorSeverity.CRITICAL,
                    message="No labour or material cost columns found",
                    suggestion="Ensure spreadsheet has either labour columns or material cost columns",
                )
            )

        # Validate individual items and detect conflicts
        labour_material_conflicts = _detect_labour_material_conflicts(
            df, labour_col, material_total_col, material_item_col
        )
        errors.extend(labour_material_conflicts)

        # Validate pricing against company defaults
        pricing_warnings = _validate_pricing_consistency(path, df)
        warnings.extend(pricing_warnings)

        # Check totals validation
        totals_warnings = _validate_totals_consistency(df, labour_col)
        warnings.extend(totals_warnings)

    except Exception as e:
        critical_issues.append(
            ValidationError(
                error_type=ErrorType.INVALID_SHEET_STRUCTURE,
                severity=ErrorSeverity.CRITICAL,
                message=f"Unexpected error during validation: {str(e)}",
            )
        )

    return _create_validation_report(critical_issues, errors, warnings, df)


def _detect_labour_material_conflicts(
    df, labour_col, material_total_col, material_item_col
) -> List[ValidationError]:
    """Detect items that have both labour and material costs."""
    conflicts = []

    if not labour_col or (not material_total_col and not material_item_col):
        return conflicts  # No conflict possible if missing columns

    for idx in range(min(45, len(df))):
        row = df.iloc[idx]
        excel_row = idx + 1

        # Check if this is a valid item
        if not _is_valid_item(row):
            continue
        # Check for conflict
        has_labour = _d(row.get(labour_col, 0)) > 0
        has_material = (
            _d(row.get(material_total_col, 0)) > 0
            or _d(row.get(material_item_col, 0)) > 0
        )

        if has_labour and has_material:
            description = str(row.get("Description", "")).strip()
            conflicts.append(
                ValidationError(
                    error_type=ErrorType.LABOUR_MATERIAL_CONFLICT,
                    severity=ErrorSeverity.ERROR,  # Blocking error - incorrect spreadsheet format
                    message=f"Item '{description}' has both labour and material costs",
                    row_number=excel_row,
                    suggestion="Remove either labour time or material costs - each item should be either labour OR material, not both",
                )
            )

    return conflicts


def _validate_pricing_consistency(path: str, df) -> List[ValidationError]:
    """Validate pricing against company defaults and pricing details sheet."""
    warnings = []

    try:
        # Get company defaults
        try:
            from apps.workflow.models import CompanyDefaults

            defaults = CompanyDefaults.get_solo()
            if defaults:
                expected_charge = defaults.charge_out_rate
                expected_markup = defaults.materials_markup
            else:
                expected_charge = DEFAULT_CHARGE_OUT_RATE
                expected_markup = DEFAULT_MATERIALS_MARKUP
        except (ImportError, Exception):
            # expected_wage = DEFAULT_WAGE_RATE  # Not used
            expected_charge = DEFAULT_CHARGE_OUT_RATE
            expected_markup = DEFAULT_MATERIALS_MARKUP

        # Check pricing details sheet
        try:
            pricing_df = pd.read_excel(path, sheet_name="pricing details - inhouse")

            # Find labour cost and margin
            labour_cost_row = None
            margin_row = None

            for idx, row in pricing_df.iterrows():
                desc = str(row.get("Description", "")).strip().lower()
                if "labour cost" in desc:
                    labour_cost_row = row
                elif "margin" in desc:
                    margin_row = row

            # Validate labour cost
            if labour_cost_row is not None:
                actual_labour_cost = _d(labour_cost_row.get("amount", 0))
                if abs(actual_labour_cost - expected_charge) > Decimal("1.00"):
                    warnings.append(
                        ValidationError(
                            error_type=ErrorType.CHARGE_RATE_MISMATCH,
                            severity=ErrorSeverity.WARNING,
                            message=f"Labour cost in pricing details (${actual_labour_cost}) doesn't match company charge-out rate (${expected_charge})",
                            expected_value=float(expected_charge),
                            actual_value=float(actual_labour_cost),
                            suggestion="Update company defaults or spreadsheet pricing",
                        )
                    )

            # Validate margin
            if margin_row is not None:
                actual_margin = _d(margin_row.get("amount", 0))
                expected_margin_multiplier = 1 + expected_markup
                if abs(actual_margin - expected_margin_multiplier) > Decimal("0.05"):
                    warnings.append(
                        ValidationError(
                            error_type=ErrorType.MARKUP_MISMATCH,
                            severity=ErrorSeverity.WARNING,
                            message=f"Margin in pricing details ({actual_margin}) doesn't match company markup ({expected_margin_multiplier})",
                            expected_value=float(expected_margin_multiplier),
                            actual_value=float(actual_margin),
                            suggestion="Update company defaults or spreadsheet pricing",
                        )
                    )

        except Exception:
            # Pricing details sheet not found or readable - this is optional
            pass

    except Exception as e:
        warnings.append(
            ValidationError(
                error_type=ErrorType.PRICING_MISMATCH,
                severity=ErrorSeverity.WARNING,
                message=f"Could not validate pricing consistency: {str(e)}",
            )
        )

    return warnings


def _validate_totals_consistency(df, labour_col) -> List[ValidationError]:
    """Validate that computed totals match spreadsheet totals."""
    warnings = []

    try:
        validation_cells = find_validation_cells(df, labour_col)

        # This is a simplified validation - full validation happens during parsing
        if not validation_cells.get("total_minutes"):
            warnings.append(
                ValidationError(
                    error_type=ErrorType.TOTALS_MISMATCH,
                    severity=ErrorSeverity.WARNING,
                    message="Could not find total minutes cell for validation",
                    suggestion="Check spreadsheet format and ensure totals are present",
                )
            )

        if not validation_cells.get("labour_revenue"):
            warnings.append(
                ValidationError(
                    error_type=ErrorType.TOTALS_MISMATCH,
                    severity=ErrorSeverity.WARNING,
                    message="Could not find labour revenue cell for validation",
                    suggestion="Check spreadsheet format and ensure labour totals are present",
                )
            )

    except Exception as e:
        warnings.append(
            ValidationError(
                error_type=ErrorType.TOTALS_MISMATCH,
                severity=ErrorSeverity.WARNING,
                message=f"Could not validate totals: {str(e)}",
            )
        )

    return warnings


def _is_valid_item(row) -> bool:
    """Check if a row represents a valid item."""
    # Item number is optional - we'll auto-assign if missing or invalid
    # No need to validate item number format since we'll handle that automatically

    # Must have quantity
    quantity = row.get("quantity")
    if pd.isna(quantity) or quantity is None or quantity == 0:
        return False

    # Description is optional - if empty, we'll use item number as fallback
    return True


def _create_validation_report(
    critical_issues: List[ValidationError],
    errors: List[ValidationError],
    warnings: List[ValidationError],
    df,
) -> ValidationReport:
    """Create a validation report from collected issues."""
    is_valid = len(critical_issues) == 0 and len(errors) == 0
    can_proceed = len(critical_issues) == 0 and len(errors) == 0

    # Create summary
    summary = {
        "total_issues": len(critical_issues) + len(errors) + len(warnings),
        "critical_count": len(critical_issues),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "sheet_readable": df is not None,
        "estimated_items": (
            0
            if df is None
            else sum(
                1 for idx in range(min(45, len(df))) if _is_valid_item(df.iloc[idx])
            )
        ),
    }

    return ValidationReport(
        is_valid=is_valid,
        can_proceed=can_proceed,
        errors=errors,
        warnings=warnings,
        critical_issues=critical_issues,
        summary=summary,
    )
