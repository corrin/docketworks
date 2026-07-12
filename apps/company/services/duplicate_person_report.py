"""Find distinct Person rows that share exact identity signals."""

from collections import defaultdict
from datetime import datetime
from typing import Literal, TypedDict
from uuid import UUID

from django.db.models import Count
from django.utils import timezone

from apps.company.models import CompanyPersonLink, ContactMethod, Person

MatchKind = Literal["name", "email", "phone"]
Confidence = Literal["high", "medium", "low"]


class DuplicatePersonCompanyLink(TypedDict):
    link_id: str
    company_id: str
    company_name: str
    position: str | None
    is_primary: bool
    is_active: bool


class DuplicatePersonContactMethod(TypedDict):
    method_id: str
    method_type: str
    value: str
    normalized_value: str
    contact_label: str
    is_primary: bool


class DuplicatePersonSummary(TypedDict):
    person_id: str
    name: str
    email: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    company_links: list[DuplicatePersonCompanyLink]
    contact_methods: list[DuplicatePersonContactMethod]
    job_count: int
    phone_call_count: int


class DuplicatePersonMatch(TypedDict):
    kind: MatchKind
    normalized_value: str


class DuplicatePersonCandidate(TypedDict):
    confidence: Confidence
    matches: list[DuplicatePersonMatch]
    shared_company_ids: list[str]
    first_person: DuplicatePersonSummary
    second_person: DuplicatePersonSummary


class DuplicatePersonReportSummary(TypedDict):
    candidate_pairs: int
    people_flagged: int
    high: int
    medium: int
    low: int


class DuplicatePersonReport(TypedDict):
    duplicate_people: list[DuplicatePersonCandidate]
    summary: DuplicatePersonReportSummary
    checked_at: datetime


def normalize_person_name(value: str) -> str:
    """Normalize an exact-name signal without introducing fuzzy matching."""
    return " ".join(value.split()).casefold()


def normalize_person_email(value: str | None) -> str:
    return (value or "").strip().casefold()


def _confidence(match_kinds: set[MatchKind]) -> Confidence:
    if len(match_kinds) >= 2:
        return "high"
    if "phone" in match_kinds or "email" in match_kinds:
        return "medium"
    return "low"


class DuplicatePersonReportService:
    """Build exact-signal candidate pairs for operator review."""

    def get_report(self) -> DuplicatePersonReport:
        people = list(Person.objects.order_by("id"))
        person_ids = [person.id for person in people]
        links_by_person: dict[UUID, list[CompanyPersonLink]] = defaultdict(list)
        for link in CompanyPersonLink.objects.filter(
            person_id__in=person_ids
        ).select_related("company"):
            links_by_person[link.person_id].append(link)
        methods_by_person: dict[UUID, list[ContactMethod]] = defaultdict(list)
        for method in ContactMethod.objects.filter(person_id__in=person_ids):
            if method.person_id is None:
                raise RuntimeError(f"Person contact method {method.id} has no Person")
            methods_by_person[method.person_id].append(method)
        job_counts = self._job_counts(person_ids)
        call_counts = self._call_counts(person_ids)
        summaries = {
            person.id: self._person_summary(
                person,
                links=links_by_person[person.id],
                methods=methods_by_person[person.id],
                job_count=job_counts.get(person.id, 0),
                phone_call_count=call_counts.get(person.id, 0),
            )
            for person in people
        }

        signal_owners: dict[tuple[MatchKind, str], set[UUID]] = defaultdict(set)
        for person in people:
            name = normalize_person_name(person.name)
            if name:
                signal_owners[("name", name)].add(person.id)

            email = normalize_person_email(person.email)
            if email:
                signal_owners[("email", email)].add(person.id)

            for method in methods_by_person[person.id]:
                if method.method_type == ContactMethod.MethodType.EMAIL:
                    kind: MatchKind = "email"
                elif method.method_type == ContactMethod.MethodType.PHONE:
                    kind = "phone"
                else:
                    raise ValueError(
                        f"Unknown contact method type {method.method_type!r}"
                    )
                if method.normalized_value:
                    signal_owners[(kind, method.normalized_value)].add(person.id)

        pair_matches: dict[tuple[UUID, UUID], dict[MatchKind, set[str]]] = defaultdict(
            lambda: defaultdict(set)
        )
        for (kind, normalized_value), owners in signal_owners.items():
            ordered_owners = sorted(owners, key=str)
            for first_index, first_id in enumerate(ordered_owners):
                for second_id in ordered_owners[first_index + 1 :]:
                    pair_matches[(first_id, second_id)][kind].add(normalized_value)

        candidates = [
            self._candidate(pair, matches, summaries)
            for pair, matches in pair_matches.items()
        ]
        confidence_order: dict[Confidence, int] = {"high": 0, "medium": 1, "low": 2}
        candidates.sort(
            key=lambda candidate: (
                confidence_order[candidate["confidence"]],
                candidate["first_person"]["name"].casefold(),
                candidate["second_person"]["name"].casefold(),
                candidate["first_person"]["person_id"],
                candidate["second_person"]["person_id"],
            )
        )
        flagged_ids = {
            person["person_id"]
            for candidate in candidates
            for person in (candidate["first_person"], candidate["second_person"])
        }
        return {
            "duplicate_people": candidates,
            "summary": {
                "candidate_pairs": len(candidates),
                "people_flagged": len(flagged_ids),
                "high": sum(c["confidence"] == "high" for c in candidates),
                "medium": sum(c["confidence"] == "medium" for c in candidates),
                "low": sum(c["confidence"] == "low" for c in candidates),
            },
            "checked_at": timezone.now(),
        }

    @staticmethod
    def _job_counts(person_ids: list[UUID]) -> dict[UUID, int]:
        from apps.job.models import Job

        return {
            person_id: count
            for person_id, count in Job.objects.filter(person_id__in=person_ids)
            .values_list("person_id")
            .annotate(count=Count("id"))
        }

    @staticmethod
    def _call_counts(person_ids: list[UUID]) -> dict[UUID, int]:
        from apps.crm.models import PhoneCallRecord

        return {
            person_id: count
            for person_id, count in PhoneCallRecord.objects.filter(
                person_id__in=person_ids
            )
            .values_list("person_id")
            .annotate(count=Count("id"))
        }

    @staticmethod
    def _person_summary(
        person: Person,
        *,
        links: list[CompanyPersonLink],
        methods: list[ContactMethod],
        job_count: int,
        phone_call_count: int,
    ) -> DuplicatePersonSummary:
        link_summaries: list[DuplicatePersonCompanyLink] = [
            {
                "link_id": str(link.id),
                "company_id": str(link.company_id),
                "company_name": link.company.name,
                "position": link.position,
                "is_primary": link.is_primary,
                "is_active": link.is_active,
            }
            for link in sorted(
                links,
                key=lambda item: (item.company.name.casefold(), str(item.id)),
            )
        ]
        method_summaries: list[DuplicatePersonContactMethod] = [
            {
                "method_id": str(method.id),
                "method_type": method.method_type,
                "value": method.value,
                "normalized_value": method.normalized_value,
                "contact_label": method.label,
                "is_primary": method.is_primary,
            }
            for method in sorted(
                methods,
                key=lambda item: (
                    item.method_type,
                    item.normalized_value,
                    str(item.id),
                ),
            )
        ]
        return {
            "person_id": str(person.id),
            "name": person.name,
            "email": person.email,
            "is_active": person.is_active,
            "created_at": person.created_at,
            "updated_at": person.updated_at,
            "company_links": link_summaries,
            "contact_methods": method_summaries,
            "job_count": job_count,
            "phone_call_count": phone_call_count,
        }

    @staticmethod
    def _candidate(
        pair: tuple[UUID, UUID],
        matches_by_kind: dict[MatchKind, set[str]],
        summaries: dict[UUID, DuplicatePersonSummary],
    ) -> DuplicatePersonCandidate:
        first_id, second_id = pair
        match_kind_order: tuple[MatchKind, ...] = ("name", "email", "phone")
        matches: list[DuplicatePersonMatch] = [
            {"kind": kind, "normalized_value": value}
            for kind in match_kind_order
            for value in sorted(matches_by_kind.get(kind, set()))
        ]
        first = summaries[first_id]
        second = summaries[second_id]
        first_companies = {link["company_id"] for link in first["company_links"]}
        second_companies = {link["company_id"] for link in second["company_links"]}
        return {
            "confidence": _confidence(set(matches_by_kind)),
            "matches": matches,
            "shared_company_ids": sorted(first_companies & second_companies),
            "first_person": first,
            "second_person": second,
        }
