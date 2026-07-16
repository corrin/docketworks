"""Group duplicate Company and Person records by corroborated identity evidence."""

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from hashlib import sha256
from typing import Literal, TypedDict
from uuid import UUID

from django.db import models
from django.utils import timezone
from rapidfuzz import fuzz

from apps.company.models import Company, CompanyPersonLink, ContactMethod, Person
from apps.company.services.duplicate_person_report import (
    DuplicatePersonSummary,
    normalize_person_email,
    normalize_person_name,
    person_names_compatible,
)

EntityKind = Literal["company", "person"]
Recommendation = Literal["merge", "review"]
EvidenceKind = Literal[
    "name",
    "email",
    "email_domain",
    "phone",
    "address",
    "shared_person",
]
Pair = tuple[UUID, UUID]

MAX_RARE_OWNERS = 3
MAX_AUTO_GROUP_SIZE = 5
COMPANY_NAME_SIMILARITY = 90
PERSON_NAME_SIMILARITY = 85

PUBLIC_EMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "hotmail.com",
        "icloud.com",
        "outlook.com",
        "xtra.co.nz",
        "yahoo.co.nz",
        "yahoo.com",
    }
)
GENERIC_EMAIL_LOCAL_PARTS = frozenset(
    {
        "accounts",
        "admin",
        "contact",
        "enquiries",
        "enquiry",
        "info",
        "office",
        "reception",
        "sales",
    }
)
COMPANY_NAME_NOISE = frozenset(
    {
        "co",
        "company",
        "inc",
        "incorporated",
        "limited",
        "ltd",
        "llc",
        "new",
        "nz",
        "zealand",
    }
)


class DuplicateIdentityEvidence(TypedDict):
    kind: EvidenceKind
    normalized_value: str
    owner_count: int


class DuplicateCompanyMember(TypedDict):
    company_id: str
    name: str
    email: str | None
    address: str | None
    allow_jobs: bool
    is_account_customer: bool
    is_supplier: bool
    xero_archived: bool
    job_count: int
    contact_names: list[str]


class DuplicatePersonMember(DuplicatePersonSummary):
    pass


class DuplicateCompanyGroup(TypedDict):
    group_id: str
    fingerprint: str
    recommendation: Recommendation
    reason_codes: list[str]
    canonical_id: str | None
    members: list[DuplicateCompanyMember]
    evidence: list[DuplicateIdentityEvidence]


class DuplicatePersonGroup(TypedDict):
    group_id: str
    fingerprint: str
    recommendation: Recommendation
    reason_codes: list[str]
    canonical_id: str | None
    members: list[DuplicatePersonMember]
    evidence: list[DuplicateIdentityEvidence]


class DuplicateIdentityReportSummary(TypedDict):
    company_merge_groups: int
    company_review_groups: int
    person_merge_groups: int
    person_review_groups: int


class DuplicateIdentityReport(TypedDict):
    company_groups: list[DuplicateCompanyGroup]
    person_groups: list[DuplicatePersonGroup]
    summary: DuplicateIdentityReportSummary
    checked_at: datetime


def _ordered_pair(first_id: UUID, second_id: UUID) -> Pair:
    if str(first_id) < str(second_id):
        return first_id, second_id
    return second_id, first_id


def _normalise_text(value: str | None) -> str:
    folded = unicodedata.normalize("NFKC", value or "").casefold()
    return " ".join(re.sub(r"[^\w]+", " ", folded).split())


def normalize_company_name(value: str) -> str:
    """Remove presentation/legal noise while retaining the business identity."""
    normalized = _normalise_text(value.replace("&", " and ").replace("+", " plus "))
    normalized = re.sub(r"^cash\s+sale\s+", "", normalized)
    tokens = normalized.split()
    while tokens and tokens[-1] in COMPANY_NAME_NOISE:
        tokens.pop()
    return " ".join(tokens)


def normalize_company_address(value: str | None) -> str:
    """Return only sufficiently specific addresses as identity evidence."""
    normalized = _normalise_text(value)
    if not re.search(r"\d", normalized):
        return ""
    if len(normalized.split()) < 3:
        return ""
    return normalized


def _email_domain(value: str | None) -> str:
    normalized = normalize_person_email(value)
    if "@" not in normalized:
        return ""
    domain = normalized.rsplit("@", 1)[1]
    if domain in PUBLIC_EMAIL_DOMAINS:
        return ""
    return domain


def _generic_email(value: str) -> bool:
    if "@" not in value:
        return True
    return value.split("@", 1)[0] in GENERIC_EMAIL_LOCAL_PARTS


def person_names_strongly_compatible(first_name: str, second_name: str) -> bool:
    """Match exact/nickname names and restrained one-token spelling variants."""
    if person_names_compatible(first_name, second_name):
        return True
    first_tokens = normalize_person_name(first_name).split()
    second_tokens = normalize_person_name(second_name).split()
    if len(first_tokens) < 2 or len(second_tokens) < 2:
        return False

    first_given = first_tokens[0]
    second_given = second_tokens[0]
    first_surname = " ".join(first_tokens[1:])
    second_surname = " ".join(second_tokens[1:])
    given_exact = first_given == second_given
    surname_exact = first_surname == second_surname
    if not given_exact and not surname_exact:
        return False
    return (
        fuzz.WRatio(
            normalize_person_name(first_name),
            normalize_person_name(second_name),
        )
        >= PERSON_NAME_SIMILARITY
    )


def _components(edges: Iterable[Pair]) -> list[set[UUID]]:
    adjacency: dict[UUID, set[UUID]] = defaultdict(set)
    for first_id, second_id in edges:
        adjacency[first_id].add(second_id)
        adjacency[second_id].add(first_id)
    result: list[set[UUID]] = []
    visited: set[UUID] = set()
    for root_id in sorted(adjacency, key=str):
        if root_id in visited:
            continue
        component: set[UUID] = set()
        pending = [root_id]
        while pending:
            entity_id = pending.pop()
            if entity_id in component:
                continue
            component.add(entity_id)
            pending.extend(adjacency[entity_id])
        visited.update(component)
        result.append(component)
    return result


def _group_id(kind: EntityKind, member_ids: set[UUID]) -> str:
    identity = f"{kind}:" + ":".join(sorted(str(member_id) for member_id in member_ids))
    return sha256(identity.encode()).hexdigest()[:16]


def _fingerprint(
    kind: EntityKind,
    member_ids: set[UUID],
    evidence: list[DuplicateIdentityEvidence],
) -> str:
    evidence_values = [
        f"{item['kind']}={item['normalized_value']}:{item['owner_count']}"
        for item in evidence
    ]
    payload = "|".join(
        [kind, *sorted(str(member_id) for member_id in member_ids), *evidence_values]
    )
    return sha256(payload.encode()).hexdigest()


class DuplicateIdentityReportService:
    """Detect actionable duplicate identities without emitting pairwise noise."""

    def get_report(self) -> DuplicateIdentityReport:
        companies = list(
            Company.objects.filter(merged_into__isnull=True).order_by("id")
        )
        people = list(Person.objects.order_by("id"))
        company_ids = [company.id for company in companies]
        person_ids = [person.id for person in people]

        links = list(
            CompanyPersonLink.objects.filter(
                company_id__in=company_ids,
                person_id__in=person_ids,
            ).select_related("company", "person")
        )
        methods = list(
            ContactMethod.objects.filter(
                models.Q(company_id__in=company_ids)
                | models.Q(person_id__in=person_ids)
            )
        )

        links_by_company: dict[UUID, list[CompanyPersonLink]] = defaultdict(list)
        links_by_person: dict[UUID, list[CompanyPersonLink]] = defaultdict(list)
        for link in links:
            links_by_company[link.company_id].append(link)
            links_by_person[link.person_id].append(link)

        company_methods: dict[UUID, list[ContactMethod]] = defaultdict(list)
        person_methods: dict[UUID, list[ContactMethod]] = defaultdict(list)
        for method in methods:
            if method.company_id is not None:
                company_methods[method.company_id].append(method)
            elif method.person_id is not None:
                person_methods[method.person_id].append(method)
            else:
                raise RuntimeError(f"ContactMethod {method.id} has no owner")

        person_pair_evidence, person_signal_owners = self._person_pair_evidence(
            people,
            person_methods,
        )
        provisional_people = self._provisional_person_edges(
            people,
            person_pair_evidence,
            person_signal_owners,
        )
        company_pair_evidence = self._company_pair_evidence(
            companies,
            company_methods,
            links_by_person,
            provisional_people,
        )
        company_groups, effective_company = self._company_groups(
            companies,
            links_by_company,
            company_pair_evidence,
        )
        person_groups = self._person_groups(
            people,
            links_by_person,
            person_methods,
            person_pair_evidence,
            person_signal_owners,
            effective_company,
        )
        return {
            "company_groups": company_groups,
            "person_groups": person_groups,
            "summary": {
                "company_merge_groups": sum(
                    group["recommendation"] == "merge" for group in company_groups
                ),
                "company_review_groups": sum(
                    group["recommendation"] == "review" for group in company_groups
                ),
                "person_merge_groups": sum(
                    group["recommendation"] == "merge" for group in person_groups
                ),
                "person_review_groups": sum(
                    group["recommendation"] == "review" for group in person_groups
                ),
            },
            "checked_at": timezone.now(),
        }

    @staticmethod
    def _person_pair_evidence(
        people: list[Person],
        methods_by_person: dict[UUID, list[ContactMethod]],
    ) -> tuple[
        dict[Pair, dict[EvidenceKind, set[str]]],
        dict[tuple[EvidenceKind, str], set[UUID]],
    ]:
        signal_owners: dict[tuple[EvidenceKind, str], set[UUID]] = defaultdict(set)
        for person in people:
            name = normalize_person_name(person.name)
            if name:
                signal_owners[("name", name)].add(person.id)
            email = normalize_person_email(person.email)
            if email:
                signal_owners[("email", email)].add(person.id)
            for method in methods_by_person[person.id]:
                kind: EvidenceKind
                if method.method_type == ContactMethod.MethodType.EMAIL:
                    kind = "email"
                elif method.method_type == ContactMethod.MethodType.PHONE:
                    kind = "phone"
                else:
                    raise ValueError(
                        f"Unknown contact method type {method.method_type!r}"
                    )
                signal_owners[(kind, method.normalized_value)].add(person.id)

        pair_evidence: dict[Pair, dict[EvidenceKind, set[str]]] = defaultdict(
            lambda: defaultdict(set)
        )
        for (kind, value), owners in signal_owners.items():
            if kind != "name" and len(owners) > MAX_RARE_OWNERS:
                continue
            ordered = sorted(owners, key=str)
            for index, first_id in enumerate(ordered):
                for second_id in ordered[index + 1 :]:
                    pair_evidence[(first_id, second_id)][kind].add(value)
        return pair_evidence, signal_owners

    @staticmethod
    def _provisional_person_edges(
        people: list[Person],
        pair_evidence: dict[Pair, dict[EvidenceKind, set[str]]],
        signal_owners: dict[tuple[EvidenceKind, str], set[UUID]],
    ) -> set[Pair]:
        people_by_id = {person.id: person for person in people}
        result: set[Pair] = set()
        for pair, matches in pair_evidence.items():
            first = people_by_id[pair[0]]
            second = people_by_id[pair[1]]
            compatible = person_names_strongly_compatible(first.name, second.name)
            rare_email = any(
                len(signal_owners[("email", value)]) <= MAX_RARE_OWNERS
                and not _generic_email(value)
                for value in matches.get("email", set())
            )
            rare_phone = any(
                len(signal_owners[("phone", value)]) <= MAX_RARE_OWNERS
                for value in matches.get("phone", set())
            )
            if compatible and (rare_email or rare_phone):
                result.add(pair)
        return result

    @staticmethod
    def _company_pair_evidence(
        companies: list[Company],
        methods_by_company: dict[UUID, list[ContactMethod]],
        links_by_person: dict[UUID, list[CompanyPersonLink]],
        strong_person_edges: set[Pair],
    ) -> dict[Pair, dict[EvidenceKind, set[str]]]:
        signal_owners: dict[tuple[EvidenceKind, str], set[UUID]] = defaultdict(set)
        for company in companies:
            name = normalize_company_name(company.name)
            if name:
                signal_owners[("name", name)].add(company.id)
            address = normalize_company_address(company.address)
            if address:
                signal_owners[("address", address)].add(company.id)
            email_values = {normalize_person_email(company.email)}
            email_values.update(
                method.normalized_value
                for method in methods_by_company[company.id]
                if method.method_type == ContactMethod.MethodType.EMAIL
            )
            for email in email_values - {""}:
                signal_owners[("email", email)].add(company.id)
                domain = _email_domain(email)
                if domain:
                    signal_owners[("email_domain", domain)].add(company.id)
            for method in methods_by_company[company.id]:
                if method.method_type == ContactMethod.MethodType.PHONE:
                    signal_owners[("phone", method.normalized_value)].add(company.id)

        pair_evidence: dict[Pair, dict[EvidenceKind, set[str]]] = defaultdict(
            lambda: defaultdict(set)
        )
        for (kind, value), owners in signal_owners.items():
            if kind != "name" and len(owners) > MAX_RARE_OWNERS:
                continue
            ordered = sorted(owners, key=str)
            for index, first_id in enumerate(ordered):
                for second_id in ordered[index + 1 :]:
                    pair_evidence[(first_id, second_id)][kind].add(value)

        for person_pair in strong_person_edges:
            first_links = links_by_person[person_pair[0]]
            second_links = links_by_person[person_pair[1]]
            for first_link in first_links:
                for second_link in second_links:
                    if first_link.company_id == second_link.company_id:
                        continue
                    company_pair = _ordered_pair(
                        first_link.company_id,
                        second_link.company_id,
                    )
                    pair_evidence[company_pair]["shared_person"].add(
                        f"{person_pair[0]}:{person_pair[1]}"
                    )

        return pair_evidence

    def _company_groups(
        self,
        companies: list[Company],
        links_by_company: dict[UUID, list[CompanyPersonLink]],
        pair_evidence: dict[Pair, dict[EvidenceKind, set[str]]],
    ) -> tuple[list[DuplicateCompanyGroup], dict[UUID, UUID]]:
        companies_by_id = {company.id: company for company in companies}
        auto_edges: set[Pair] = set()
        review_edges: set[Pair] = set()
        reasons_by_pair: dict[Pair, set[str]] = defaultdict(set)
        for pair, matches in pair_evidence.items():
            first = companies_by_id[pair[0]]
            second = companies_by_id[pair[1]]
            exact_name = bool(matches.get("name"))
            name_similarity = fuzz.WRatio(
                normalize_company_name(first.name),
                normalize_company_name(second.name),
            )
            organisation_families = {
                "email" if kind in {"email", "email_domain"} else kind
                for kind in set(matches)
                & {
                    "email",
                    "email_domain",
                    "phone",
                    "address",
                }
            }
            shared_person_count = len(matches.get("shared_person", set()))
            if exact_name:
                reasons_by_pair[pair].add("exact_company_name")
            if name_similarity >= COMPANY_NAME_SIMILARITY:
                reasons_by_pair[pair].add("similar_company_name")
            if organisation_families:
                reasons_by_pair[pair].add("shared_organisation_identity")
            if shared_person_count:
                reasons_by_pair[pair].add("shared_person_identity")

            strong = exact_name or (
                name_similarity >= COMPANY_NAME_SIMILARITY
                and bool(organisation_families or shared_person_count)
            )
            if strong:
                auto_edges.add(pair)
            elif shared_person_count or len(organisation_families) >= 2:
                review_edges.add(pair)
            else:
                # A lone domain/email/phone/address is useful corroboration but
                # not an actionable duplicate on its own. Related companies,
                # branches, co-tenants, and shared office details are common
                # enough that surfacing every such pair recreates the review
                # explosion this report exists to prevent.
                continue

        auto_components = _components(auto_edges)
        oversized_members = set().union(
            *(
                component
                for component in auto_components
                if len(component) > MAX_AUTO_GROUP_SIZE
            ),
            set(),
        )
        accepted_auto = [
            component
            for component in auto_components
            if len(component) <= MAX_AUTO_GROUP_SIZE
        ]
        if oversized_members:
            for pair in auto_edges:
                if pair[0] in oversized_members or pair[1] in oversized_members:
                    review_edges.add(pair)
                    reasons_by_pair[pair].add("oversized_component")

        effective_company: dict[UUID, UUID] = {
            company.id: company.id for company in companies
        }
        for component in accepted_auto:
            canonical = min(
                (companies_by_id[company_id] for company_id in component),
                key=lambda company: self._company_rank(
                    company,
                    links_by_company[company.id],
                ),
            )
            for company_id in component:
                effective_company[company_id] = canonical.id

        review_edges = {
            pair
            for pair in review_edges
            if effective_company[pair[0]] != effective_company[pair[1]]
        }
        review_components = _components(review_edges)
        groups = [
            self._company_group(
                component,
                "merge",
                companies_by_id,
                links_by_company,
                pair_evidence,
                reasons_by_pair,
            )
            for component in accepted_auto
        ]
        groups.extend(
            self._company_group(
                component,
                "review",
                companies_by_id,
                links_by_company,
                pair_evidence,
                reasons_by_pair,
            )
            for component in review_components
        )
        groups.sort(
            key=lambda group: (
                group["recommendation"] != "merge",
                group["members"][0]["name"].casefold(),
                group["group_id"],
            )
        )
        return groups, effective_company

    @staticmethod
    def _company_rank(
        company: Company,
        links: list[CompanyPersonLink],
    ) -> tuple[bool, bool, bool, int, object, str]:
        from apps.job.models import Job

        return (
            company.xero_archived,
            not company.allow_jobs,
            normalize_company_name(company.name) != _normalise_text(company.name),
            -(Job.objects.filter(company=company).count() + len(links)),
            company.django_created_at,
            str(company.id),
        )

    def _company_group(
        self,
        member_ids: set[UUID],
        recommendation: Recommendation,
        companies_by_id: dict[UUID, Company],
        links_by_company: dict[UUID, list[CompanyPersonLink]],
        pair_evidence: dict[Pair, dict[EvidenceKind, set[str]]],
        reasons_by_pair: dict[Pair, set[str]],
    ) -> DuplicateCompanyGroup:
        companies = [companies_by_id[company_id] for company_id in member_ids]
        canonical = min(
            companies,
            key=lambda company: self._company_rank(
                company,
                links_by_company[company.id],
            ),
        )
        evidence = self._evidence_for_members(member_ids, pair_evidence)
        reason_codes = sorted(
            {
                reason
                for pair, reasons in reasons_by_pair.items()
                if set(pair) <= member_ids
                for reason in reasons
            }
        )
        if recommendation == "review" and reason_codes == ["shared_person_identity"]:
            reason_codes = ["shared_person_only"]
        return {
            "group_id": _group_id("company", member_ids),
            "fingerprint": _fingerprint("company", member_ids, evidence),
            "recommendation": recommendation,
            "reason_codes": reason_codes,
            "canonical_id": str(canonical.id) if recommendation == "merge" else None,
            "members": [
                self._company_member(company, links_by_company[company.id])
                for company in sorted(companies, key=lambda item: item.name.casefold())
            ],
            "evidence": evidence,
        }

    @staticmethod
    def _company_member(
        company: Company,
        links: list[CompanyPersonLink],
    ) -> DuplicateCompanyMember:
        from apps.job.models import Job

        return {
            "company_id": str(company.id),
            "name": company.name,
            "email": company.email,
            "address": company.address,
            "allow_jobs": company.allow_jobs,
            "is_account_customer": company.is_account_customer,
            "is_supplier": company.is_supplier,
            "xero_archived": company.xero_archived,
            "job_count": Job.objects.filter(company=company).count(),
            "contact_names": sorted(
                {link.person.name for link in links},
                key=str.casefold,
            ),
        }

    def _person_groups(
        self,
        people: list[Person],
        links_by_person: dict[UUID, list[CompanyPersonLink]],
        methods_by_person: dict[UUID, list[ContactMethod]],
        pair_evidence: dict[Pair, dict[EvidenceKind, set[str]]],
        signal_owners: dict[tuple[EvidenceKind, str], set[UUID]],
        effective_company: dict[UUID, UUID],
    ) -> list[DuplicatePersonGroup]:
        people_by_id = {person.id: person for person in people}
        auto_edges: set[Pair] = set()
        review_edges: set[Pair] = set()
        reasons_by_pair: dict[Pair, set[str]] = defaultdict(set)
        for pair, matches in pair_evidence.items():
            first = people_by_id[pair[0]]
            second = people_by_id[pair[1]]
            first_companies = {
                effective_company[link.company_id] for link in links_by_person[first.id]
            }
            second_companies = {
                effective_company[link.company_id]
                for link in links_by_person[second.id]
            }
            same_company = bool(first_companies & second_companies)
            exact_name = bool(matches.get("name"))
            compatible = person_names_strongly_compatible(first.name, second.name)
            rare_email = any(
                len(signal_owners[("email", value)]) <= MAX_RARE_OWNERS
                and not _generic_email(value)
                for value in matches.get("email", set())
            )
            rare_phone = any(
                len(signal_owners[("phone", value)]) <= MAX_RARE_OWNERS
                for value in matches.get("phone", set())
            )
            if same_company and exact_name:
                auto_edges.add(pair)
                reasons_by_pair[pair].add("same_company_exact_name")
            elif compatible and (rare_email or rare_phone):
                auto_edges.add(pair)
                reasons_by_pair[pair].add("compatible_name_and_contact")
            elif rare_email or rare_phone:
                review_edges.add(pair)
                reasons_by_pair[pair].add("conflicting_names_shared_contact")
            else:
                continue

        auto_components = _components(auto_edges)
        accepted_auto = [
            component
            for component in auto_components
            if len(component) <= MAX_AUTO_GROUP_SIZE
        ]
        oversized = [
            component
            for component in auto_components
            if len(component) > MAX_AUTO_GROUP_SIZE
        ]
        for component in oversized:
            ordered = sorted(component, key=str)
            for index, first_id in enumerate(ordered):
                for second_id in ordered[index + 1 :]:
                    review_edges.add((first_id, second_id))
                    reasons_by_pair[(first_id, second_id)].add("oversized_component")

        auto_owner: dict[UUID, UUID] = {}
        for component in accepted_auto:
            root = min(component, key=str)
            for person_id in component:
                auto_owner[person_id] = root
        review_edges = {
            pair
            for pair in review_edges
            if auto_owner.get(pair[0], pair[0]) != auto_owner.get(pair[1], pair[1])
        }
        review_components = _components(review_edges)
        groups = [
            self._person_group(
                component,
                "merge",
                people_by_id,
                links_by_person,
                methods_by_person,
                pair_evidence,
                reasons_by_pair,
            )
            for component in accepted_auto
        ]
        groups.extend(
            self._person_group(
                component,
                "review",
                people_by_id,
                links_by_person,
                methods_by_person,
                pair_evidence,
                reasons_by_pair,
            )
            for component in review_components
        )
        groups.sort(
            key=lambda group: (
                group["recommendation"] != "merge",
                group["members"][0]["name"].casefold(),
                group["group_id"],
            )
        )
        return groups

    @staticmethod
    def _person_rank(
        person: Person,
        links: list[CompanyPersonLink],
        methods: list[ContactMethod],
    ) -> tuple[bool, int, int, bool, object, str]:
        from apps.crm.models import PhoneCallRecord
        from apps.job.models import Job

        activity = (
            Job.objects.filter(person=person).count()
            + PhoneCallRecord.objects.filter(person=person).count()
        )
        return (
            not person.is_active,
            -activity,
            -(len(links) + len(methods)),
            len(normalize_person_name(person.name).split()) < 2,
            person.created_at,
            str(person.id),
        )

    def _person_group(
        self,
        member_ids: set[UUID],
        recommendation: Recommendation,
        people_by_id: dict[UUID, Person],
        links_by_person: dict[UUID, list[CompanyPersonLink]],
        methods_by_person: dict[UUID, list[ContactMethod]],
        pair_evidence: dict[Pair, dict[EvidenceKind, set[str]]],
        reasons_by_pair: dict[Pair, set[str]],
    ) -> DuplicatePersonGroup:
        people = [people_by_id[person_id] for person_id in member_ids]
        canonical = min(
            people,
            key=lambda person: self._person_rank(
                person,
                links_by_person[person.id],
                methods_by_person[person.id],
            ),
        )
        evidence = self._evidence_for_members(member_ids, pair_evidence)
        return {
            "group_id": _group_id("person", member_ids),
            "fingerprint": _fingerprint("person", member_ids, evidence),
            "recommendation": recommendation,
            "reason_codes": sorted(
                {
                    reason
                    for pair, reasons in reasons_by_pair.items()
                    if set(pair) <= member_ids
                    for reason in reasons
                }
            ),
            "canonical_id": str(canonical.id) if recommendation == "merge" else None,
            "members": [
                self._person_member(
                    person,
                    links_by_person[person.id],
                    methods_by_person[person.id],
                )
                for person in sorted(people, key=lambda item: item.name.casefold())
            ],
            "evidence": evidence,
        }

    @staticmethod
    def _person_member(
        person: Person,
        links: list[CompanyPersonLink],
        methods: list[ContactMethod],
    ) -> DuplicatePersonMember:
        from apps.crm.models import PhoneCallRecord
        from apps.job.models import Job

        return {
            "person_id": str(person.id),
            "name": person.name,
            "email": person.email,
            "is_active": person.is_active,
            "created_at": person.created_at,
            "updated_at": person.updated_at,
            "company_links": [
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
            ],
            "contact_methods": [
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
            ],
            "job_count": Job.objects.filter(person=person).count(),
            "phone_call_count": PhoneCallRecord.objects.filter(person=person).count(),
        }

    @staticmethod
    def _evidence_for_members(
        member_ids: set[UUID],
        pair_evidence: dict[Pair, dict[EvidenceKind, set[str]]],
    ) -> list[DuplicateIdentityEvidence]:
        values: dict[tuple[EvidenceKind, str], set[UUID]] = defaultdict(set)
        for pair, matches in pair_evidence.items():
            if not set(pair) <= member_ids:
                continue
            for kind, normalized_values in matches.items():
                for normalized_value in normalized_values:
                    values[(kind, normalized_value)].update(pair)
        return [
            {
                "kind": kind,
                "normalized_value": normalized_value,
                "owner_count": len(owners),
            }
            for (kind, normalized_value), owners in sorted(
                values.items(),
                key=lambda item: (item[0][0], item[0][1]),
            )
        ]
