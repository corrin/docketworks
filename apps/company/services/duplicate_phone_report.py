"""Data Quality report: phone numbers that break the one-number-one-company rule.

Surfaces the two ways a phone number can be mis-owned, for manual clean-up:
- ``cross_client`` — a number whose effective companies (``COALESCE(company_id,
  contact.company_id)``) number more than one (the grandfathered pre-existing links).
- ``internal_line`` — a company/contact phone method whose number is one of the
  company's own internal ``PhoneEndpoint`` lines (e.g. a staff line mis-filed as a
  customer contact).
"""

from datetime import datetime
from typing import TypedDict

from django.db.models import Count
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.company.models import ClientContactMethod
from apps.crm.models import PhoneEndpoint


class DuplicatePhoneOwner(TypedDict):
    method_id: str
    owner_kind: str
    owner_name: str
    effective_client_id: str | None


class DuplicatePhoneIssue(TypedDict):
    normalized_value: str
    issue: str
    endpoint_label: str | None
    owners: list[DuplicatePhoneOwner]


class DuplicatePhoneSummary(TypedDict):
    cross_client: int
    internal_line: int


class DuplicatePhonesReport(TypedDict):
    duplicate_phones: list[DuplicatePhoneIssue]
    summary: DuplicatePhoneSummary
    checked_at: datetime


class DuplicatePhoneReportService:
    """Builds the "Duplicate phones" data-quality report."""

    def get_report(self) -> DuplicatePhonesReport:
        cross_company = self._cross_company_conflicts()
        internal_line = self._internal_line_collisions()
        return {
            "duplicate_phones": cross_company + internal_line,
            "summary": {
                "cross_client": len(cross_company),
                "internal_line": len(internal_line),
            },
            "checked_at": timezone.now(),
        }

    def _cross_company_conflicts(self) -> list[DuplicatePhoneIssue]:
        phones = ClientContactMethod.objects.filter(
            method_type=ClientContactMethod.MethodType.PHONE
        )
        conflict_numbers = [
            row["normalized_value"]
            for row in phones.values("normalized_value")
            .annotate(
                companies=Count(
                    Coalesce("company_id", "contact__company_id"), distinct=True
                )
            )
            .filter(companies__gt=1)
        ]
        if not conflict_numbers:
            return []
        grouped: dict[str, list[DuplicatePhoneOwner]] = {}
        for method in (
            phones.filter(normalized_value__in=conflict_numbers)
            .select_related("company", "contact", "contact__company")
            .order_by("normalized_value", "id")
        ):
            grouped.setdefault(method.normalized_value, []).append(self._owner(method))
        return [
            {
                "normalized_value": number,
                "issue": "cross_client",
                "endpoint_label": None,
                "owners": owners,
            }
            for number, owners in grouped.items()
        ]

    def _internal_line_collisions(self) -> list[DuplicatePhoneIssue]:
        endpoint_labels = dict(
            PhoneEndpoint.objects.filter(is_active=True).values_list(
                "normalized_number", "label"
            )
        )
        if not endpoint_labels:
            return []
        return [
            {
                "normalized_value": method.normalized_value,
                "issue": "internal_line",
                "endpoint_label": endpoint_labels[method.normalized_value],
                "owners": [self._owner(method)],
            }
            for method in (
                ClientContactMethod.objects.filter(
                    method_type=ClientContactMethod.MethodType.PHONE,
                    normalized_value__in=list(endpoint_labels),
                )
                .select_related("company", "contact", "contact__company")
                .order_by("normalized_value", "id")
            )
        ]

    @staticmethod
    def _owner(method: ClientContactMethod) -> DuplicatePhoneOwner:
        effective_company_id = method.owner_company_id()
        return {
            "method_id": str(method.id),
            "owner_kind": "company" if method.company_id else "contact",
            "owner_name": method.owner_display_name(),
            "effective_client_id": (
                str(effective_company_id) if effective_company_id else None
            ),
        }
