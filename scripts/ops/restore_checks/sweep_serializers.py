#!/usr/bin/env python
"""Comprehensive wire-contract testing script.

Tests that restored production data can be turned into every major API
response shape without crashing. Crucial after data restores or schema
changes: a row that full_clean() accepts can still blow up the transform
that turns it into a response body (a stale enum value, a JSON field with
an unexpected shape, ...).

Deviation from v1: v1 instantiated Django REST Framework serializers
directly. v2 has no DRF serializers — every response is a Ninja Schema built
from a plain dict a service function assembles (ADR 0039, one implementation
per concept). Each test below calls the same service function the real API
route calls, then validates the schema against its output, so this exercises
exactly the wire-contract-building code the API uses rather than a duplicate.

v1's TimesheetCostLineSerializer has no batch-friendly v2 counterpart: the
nearest equivalent, TimesheetCostLineOut, is built per (staff, date) pair by
apps.timesheet.services.workshop_timesheet_service.management_day_data(), not
from a flat CostLine queryset. This script instead validates every "time"
CostLine through the generic CostLineOut pipeline (job_service.cost_line_data)
that every cost line — timesheet or not — already goes through elsewhere.

Usage:
    uv run python -m scripts.ops.restore_checks.sweep_serializers [--verbose] [--serializer <name>]

Examples:
    uv run python -m scripts.ops.restore_checks.sweep_serializers
    uv run python -m scripts.ops.restore_checks.sweep_serializers --verbose
    uv run python -m scripts.ops.restore_checks.sweep_serializers --serializer job
"""

import argparse
import os
import sys
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, TypedDict

# scripts/ops/restore_checks/ is three levels below the repo root; see
# scripts/ops/setup_dev_logins.py for why this is inserted explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from ninja import Schema  # noqa: E402 -- Django must be configured first

from apps.accounts.models import Staff  # noqa: E402
from apps.accounts.schemas import StaffListItemOut  # noqa: E402
from apps.company.models import Company, ContactMethod  # noqa: E402
from apps.company.schemas import CompanyDetailResponse  # noqa: E402
from apps.company.services.company_rest_service import (  # noqa: E402
    CompanyRestService,
    annotated_with_phone,
)
from apps.job.models import CostLine, CostSet, Job  # noqa: E402
from apps.job.schemas import CostLineOut, CostSetOut, JobDetail, KanbanJobOut  # noqa: E402
from apps.job.services import job_service, kanban_service  # noqa: E402
from apps.purchasing.models import PurchaseOrder  # noqa: E402
from apps.purchasing.schemas import PurchaseOrderDetail  # noqa: E402
from apps.purchasing.services.purchase_order_service import (  # noqa: E402
    purchase_order_detail_data,
)

EXAMPLE_CAP = 3


class SerializerResult(TypedDict):
    """One test method's outcome, matching v1's result shape."""

    name: str
    total: int
    success: int
    failed: int
    failures: list[dict[str, str]]
    duration: float
    status: str


def _test_batch(
    name: str,
    items: Iterable[Any],
    total_count: int,
    build_and_validate: Callable[[Any], object],
    *,
    verbose: bool,
) -> SerializerResult:
    """Build and validate the wire schema for every item, reporting failures."""
    if total_count == 0:
        return {
            "name": name,
            "total": 0,
            "success": 0,
            "failed": 0,
            "failures": [],
            "duration": 0.0,
            "status": "SKIPPED - No data",
        }

    print(f"Testing {name} ({total_count} records)...")
    start_time = time.time()
    success_count = 0
    failed_items: list[dict[str, str]] = []

    for i, item in enumerate(items):
        try:
            build_and_validate(item)
            success_count += 1
            if verbose and (i + 1) % 100 == 0:
                print(f"  Processed {i + 1}/{total_count}...")
        except Exception as exc:  # noqa: BLE001 -- ADR 0043: this diagnostic
            # sweep exists to catalogue every failure across uncontrolled
            # restored data, not to stop at the first one nobody anticipated
            # (development hit exactly that: an unannotated Company property
            # raised a plain RuntimeError, outside any narrower catch this
            # function could have named up front). The repo's no-blanket-catch
            # rule targets production handlers that hide a cause; here the
            # catch IS the report — every exception becomes one recorded row
            # and the loop continues to the next item and the next category.
            error_info = {
                "item_id": str(getattr(item, "id", getattr(item, "pk", "unknown"))),
                "item_str": str(item)[:100],
                "error": str(exc),
                "error_type": type(exc).__name__,
            }
            failed_items.append(error_info)
            if verbose:
                print(f"  Failed item {item}: {exc}")

    duration = time.time() - start_time
    failed_count = len(failed_items)
    status = "PASS" if failed_count == 0 else f"FAIL ({failed_count} errors)"
    print(f"  {status} - {success_count}/{total_count} serialized ({duration:.2f}s)")

    return {
        "name": name,
        "total": total_count,
        "success": success_count,
        "failed": failed_count,
        "failures": failed_items,
        "duration": duration,
        "status": status,
    }


def _validated(schema: type[Schema], data: object) -> None:
    """Round-trip a dict through its schema, raising on the first violation."""
    schema.model_validate(data)


class SerializerTester:
    """Wire-contract testing over restored data."""

    def __init__(self, *, verbose: bool = False) -> None:
        self.verbose = verbose
        self.results: dict[str, SerializerResult] = {}

    def test_job(self) -> SerializerResult:
        """Test JobDetail via job_service.job_detail_data (JobSerializer's v2 home)."""
        queryset = (
            Job.objects.all()
            .select_related("person", "company", "latest_estimate", "latest_quote", "latest_actual")
            .prefetch_related("files", "invoices")
        )
        return _test_batch(
            "JobDetail",
            queryset.iterator(chunk_size=100),
            queryset.count(),
            lambda job: _validated(JobDetail, job_service.job_detail_data(job)),
            verbose=self.verbose,
        )

    def test_kanban(self) -> SerializerResult:
        """Test KanbanJobOut via KanbanService (KanbanJobSerializer's v2 home).

        Batches context the same way the real API route does — see
        apps/job/services/kanban_service.py's build_serialization_context.
        """
        jobs = list(
            Job.objects.filter(status__in=["quoting", "in_progress", "ready_for_delivery"])
            .select_related("person", "company", "created_by")
            .prefetch_related("people")
        )
        context = kanban_service.KanbanService.build_serialization_context(jobs)
        return _test_batch(
            "KanbanJobOut (via KanbanService)",
            jobs,
            len(jobs),
            lambda job: _validated(
                KanbanJobOut,
                kanban_service.KanbanService.serialize_job_for_api(job, context=context),
            ),
            verbose=self.verbose,
        )

    def test_costing(self) -> SerializerResult:
        """Test CostSetOut via job_service.cost_set_data (CostingSerializer's v2 home)."""
        queryset = CostSet.objects.all().select_related("job").prefetch_related("cost_lines")
        return _test_batch(
            "CostSetOut",
            queryset.iterator(chunk_size=100),
            queryset.count(),
            lambda cost_set: _validated(CostSetOut, job_service.cost_set_data(cost_set)),
            verbose=self.verbose,
        )

    def test_company(self) -> SerializerResult:
        """Test CompanyDetailResponse (CompanySerializer's v2 home), every row.

        Every company, like the other record-level sweeps: a sample let a
        company past position 500 fail detail validation while the sweep
        reported success.
        """
        queryset = Company.objects.with_invoice_summary().annotate(
            phone=ContactMethod.primary_phone_annotation(owner="company", outer_ref="pk")
        )
        return _test_batch(
            "CompanyDetailResponse",
            queryset.iterator(chunk_size=100),
            queryset.count(),
            # apps/company/api.py calls this same "private" helper directly;
            # it is the real API route's builder, not test-only reach-in.
            lambda company: _validated(
                CompanyDetailResponse,
                CompanyRestService._format_company_detail(annotated_with_phone(company)),
            ),
            verbose=self.verbose,
        )

    def test_staff(self) -> SerializerResult:
        """Test StaffListItemOut (StaffSerializer's v2 home): direct model fields."""
        queryset = Staff.objects.all()
        return _test_batch(
            "StaffListItemOut",
            queryset.iterator(chunk_size=100),
            queryset.count(),
            lambda staff: StaffListItemOut.model_validate(staff, from_attributes=True),
            verbose=self.verbose,
        )

    def test_purchase_order(self) -> SerializerResult:
        """Test PurchaseOrderDetail (PurchaseOrderDetailSerializer's v2 home)."""
        queryset = PurchaseOrder.objects.all().select_related("supplier", "pickup_address")
        return _test_batch(
            "PurchaseOrderDetail",
            queryset.iterator(chunk_size=100),
            queryset.count(),
            lambda po: _validated(PurchaseOrderDetail, purchase_order_detail_data(po)),
            verbose=self.verbose,
        )

    def test_timesheet(self) -> SerializerResult:
        """Test CostLineOut over "time"-kind lines.

        See the module docstring: v1's TimesheetCostLineSerializer has no
        flat, batch-friendly v2 equivalent, so this validates the same
        generic CostLineOut pipeline every time-kind cost line goes through.
        """
        queryset = CostLine.objects.filter(kind="time").select_related("cost_set__job")
        return _test_batch(
            "CostLineOut (kind=time)",
            queryset.iterator(chunk_size=100),
            queryset.count(),
            lambda line: _validated(CostLineOut, job_service.cost_line_data(line)),
            verbose=self.verbose,
        )

    def run_all(self, specific: str | None) -> dict[str, SerializerResult]:
        test_methods: dict[str, Callable[[], SerializerResult]] = {
            "job": self.test_job,
            "kanban": self.test_kanban,
            "costing": self.test_costing,
            "company": self.test_company,
            "staff": self.test_staff,
            "purchase_order": self.test_purchase_order,
            "timesheet": self.test_timesheet,
        }

        if specific:
            if specific not in test_methods:
                print(f"Unknown serializer: {specific}")
                print(f"Available serializers: {', '.join(test_methods.keys())}")
                return {}
            test_methods = {specific: test_methods[specific]}

        print("Starting Wire-Contract Testing")
        print("=" * 60)
        total_start = time.time()
        for test_name, test_method in test_methods.items():
            self.results[test_name] = test_method()
        self._print_summary(time.time() - total_start)
        return self.results

    def _print_summary(self, total_duration: float) -> bool:
        print("=" * 60)
        print("WIRE-CONTRACT TEST SUMMARY")
        print("=" * 60)

        total_items = 0
        total_success = 0
        total_failed = 0
        failed_serializers = []

        for test_name, result in self.results.items():
            total_items += result["total"]
            total_success += result["success"]
            total_failed += result["failed"]
            print(f"{result['status']:20} {test_name:25} ({result['success']}/{result['total']})")
            if result["failed"] > 0:
                failed_serializers.append(test_name)
                if self.verbose:
                    print("  First few failures:")
                    for failure in result["failures"][:EXAMPLE_CAP]:
                        print(f"    {failure['item_str']}: {failure['error']}")

        print("-" * 60)
        print(f"TOTALS: {total_success}/{total_items} items serialized successfully")
        print(f"DURATION: {total_duration:.2f} seconds")

        if failed_serializers:
            print(f"FAILED: {', '.join(failed_serializers)}")
            print("CRITICAL: Some wire contracts failed. Check data integrity!")
            return False
        print("ALL WIRE CONTRACTS PASSED")
        return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test the API's wire contracts against restored data"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Verbose output with detailed progress"
    )
    parser.add_argument(
        "--serializer",
        "-s",
        type=str,
        help=(
            "Test specific contract (job, kanban, costing, company, staff, "
            "purchase_order, timesheet)"
        ),
    )
    args = parser.parse_args()

    tester = SerializerTester(verbose=args.verbose)
    results = tester.run_all(args.serializer)
    success = all(result["failed"] == 0 for result in results.values())
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
