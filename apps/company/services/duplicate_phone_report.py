"""Data Quality report: phone numbers that break the one-number-one-company rule."""

from datetime import datetime
from typing import TypedDict

from django.utils import timezone

from apps.company.models import ContactMethod
from apps.crm.models import PhoneEndpoint


class DuplicatePhoneOwner(TypedDict):
    method_id: str
    owner_kind: str
    owner_name: str
    effective_company_id: str | None


class DuplicatePhoneIssue(TypedDict):
    normalized_value: str
    issue: str
    endpoint_label: str | None
    owners: list[DuplicatePhoneOwner]


class DuplicatePhoneSummary(TypedDict):
    cross_company: int
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
                "cross_company": len(cross_company),
                "internal_line": len(internal_line),
            },
            "checked_at": timezone.now(),
        }

    def _cross_company_conflicts(self) -> list[DuplicatePhoneIssue]:
        phones = ContactMethod.objects.filter(
            method_type=ContactMethod.MethodType.PHONE
        )
        companies_by_owner_by_number: dict[str, dict[tuple[str, str], set[str]]] = {}
        for method in phones.select_related("company", "person").prefetch_related(
            "person__company_links"
        ):
            if method.person_id is not None:
                owner_key = ("person", str(method.person_id))
            elif method.company_id is not None:
                owner_key = ("company", str(method.company_id))
            else:
                raise RuntimeError(f"Contact method {method.id} has no owner")
            owners = companies_by_owner_by_number.setdefault(
                method.normalized_value, {}
            )
            owners.setdefault(owner_key, set()).update(
                str(company_id) for company_id in method.owner_company_ids()
            )
        conflict_numbers = [
            number
            for number, owners in companies_by_owner_by_number.items()
            if self._owners_have_no_common_company(owners)
        ]
        if not conflict_numbers:
            return []
        grouped: dict[str, list[DuplicatePhoneOwner]] = {}
        for method in (
            phones.filter(normalized_value__in=conflict_numbers)
            .select_related("company", "person")
            .prefetch_related("person__company_links")
            .order_by("normalized_value", "id")
        ):
            grouped.setdefault(method.normalized_value, []).append(self._owner(method))
        return [
            {
                "normalized_value": number,
                "issue": "cross_company",
                "endpoint_label": None,
                "owners": owners,
            }
            for number, owners in grouped.items()
        ]

    @staticmethod
    def _owners_have_no_common_company(
        companies_by_owner: dict[tuple[str, str], set[str]],
    ) -> bool:
        if len(companies_by_owner) < 2:
            return False
        owner_company_sets = iter(companies_by_owner.values())
        common_companies = set(next(owner_company_sets))
        for company_ids in owner_company_sets:
            common_companies.intersection_update(company_ids)
        return not common_companies

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
                ContactMethod.objects.filter(
                    method_type=ContactMethod.MethodType.PHONE,
                    normalized_value__in=list(endpoint_labels),
                )
                .select_related("company", "person")
                .prefetch_related("person__company_links")
                .order_by("normalized_value", "id")
            )
        ]

    @staticmethod
    def _owner(method: ContactMethod) -> DuplicatePhoneOwner:
        effective_company_id = method.owner_company_id()
        return {
            "method_id": str(method.id),
            "owner_kind": "company" if method.company_id else "person",
            "owner_name": method.owner_display_name(),
            "effective_company_id": (
                str(effective_company_id) if effective_company_id else None
            ),
        }
