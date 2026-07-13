"""Reviewed one-time duplicate cleanup for the KAN-278 production dataset."""

from collections import defaultdict
from collections.abc import Iterable
from uuid import UUID

from apps.accounts.models import Staff
from apps.company.models import Company, CompanyPersonLink, ContactMethod, Person
from apps.company.services.company_merge_service import merge_companies
from apps.company.services.duplicate_identity_report import (
    DuplicateIdentityReportService,
)
from apps.company.services.person_merge_service import merge_people

CompanyMerge = tuple[str, str]
PersonLinkEdge = tuple[str, str]

# source Company -> canonical Company. These UUIDs are stable across the
# client->company relabel and the first-class Person migrations.
REVIEWED_COMPANY_MERGES: tuple[CompanyMerge, ...] = (
    (
        "8a0a7c59-6b87-45d7-82f6-c543b74b37db",
        "42341b19-8baf-434d-b2c9-fd0aed92a44b",
    ),  # Northland Roofs
    (
        "99c01fb4-a14e-499c-bf4f-7dd1c139242b",
        "9cca5c95-d4d1-4f7e-a781-eaea26873e06",
    ),  # ELS NZ
    (
        "0aebb7a4-e7e3-443c-a329-6fa9bf4c07a7",
        "c4fb5c65-278e-4790-9fce-acdd24a5012b",
    ),  # Interior DB
    (
        "44fec154-e91e-41e8-a406-f913740c1258",
        "94a26554-4758-4339-bfc0-f92067815d47",
    ),  # Supercity
    (
        "59cd4324-98cb-4ea1-9825-dfe01bcc39d2",
        "b52223eb-aa5d-4d94-9264-e4504baf4b38",
    ),  # New Generation Operations
    (
        "8318321c-919a-440a-96ff-87e3c43e9551",
        "b3bd1d4e-829f-47c7-a9f0-e77496835c21",
    ),  # Timeworx
    (
        "039e1bc8-9068-464b-9998-a563a69fb6df",
        "4cb5ef4e-2936-4f05-991f-cc41be8ad54d",
    ),  # Viking Builders
    (
        "92e6e04e-f8e9-4fee-ac2f-5ca375468635",
        "4d8e32e7-4e34-4e22-8169-91b9e1365579",
    ),  # Penrose Motors
    (
        "d2059e47-da19-4bc1-bcc2-ead96368860b",
        "c07dc252-d3ed-41c8-bf36-8e5d7e1da3b9",
    ),  # Marsh Cooper
    (
        "6ac46b26-2d76-4cfe-ae85-f057fb98e169",
        "15b27ab2-3b14-4eeb-bc70-a65c92a8b08a",
    ),  # Point Maintenance
    (
        "c2eda802-c67f-471e-acd0-1d01e97c2162",
        "15b27ab2-3b14-4eeb-bc70-a65c92a8b08a",
    ),  # Point Maintenance
    (
        "f642cfe5-2a0d-42c1-a7de-24ff5b5ac521",
        "0833cc79-f9a8-4537-8396-2a6b6040f9de",
    ),  # Acryfab
    (
        "ae5d6422-f67d-463a-a0f9-5f6f1e9d0d99",
        "67394ffd-13e5-4f1d-8af4-daf92d694e13",
    ),  # AZ Panels
    (
        "588a8268-394c-41a4-aa39-cfcf3903f934",
        "3fce4f6b-6211-4e18-9e26-5a64955afecf",
    ),  # Custom Controls
    (
        "f29ec9b6-4c6d-46d6-937a-78f431276c1a",
        "99568812-4f22-4f15-be24-715fb4458977",
    ),  # Cushman & Wakefield
    (
        "581b0b1c-cda6-40f9-87b9-9d56b3902a6d",
        "49bd07e9-25d1-4d33-b693-35eb2796fbdc",
    ),  # Church St Panelbeaters
    (
        "1650248c-865c-463e-bef9-4374ca74b1de",
        "1f667c71-3830-451e-96ad-90ec6f3177b2",
    ),  # Elijah Haridas
    (
        "f7a53925-1099-4c8a-b55d-e25094df4bb8",
        "0f61dc0c-c394-42d2-8d80-d4cdba9451ae",
    ),  # Richard Pryde
    (
        "4bc54f5a-d7df-4e09-9898-4c6c2dd6f18a",
        "8d35c1c1-2181-4979-8299-549a0556e48d",
    ),  # Veronica Bartlett
    (
        "24ae90b5-4cf2-4958-b1de-287930733dd5",
        "60b3f0e0-7da5-451d-9fe8-1c139f4fb826",
    ),  # DGE
    (
        "82cdb03c-2590-4cd6-95d0-288aed62e7fb",
        "245e1a32-dd55-49bd-899b-7f253774d774",
    ),  # Rauland
    (
        "19744741-ad4a-49db-b52d-18ee91b6310a",
        "d4fa0e82-8ea7-4cea-b755-0fd713f6b65e",
    ),  # Pacific Bakery
    (
        "777b7d0d-2897-480c-a295-6e2e4a984f83",
        "d4fa0e82-8ea7-4cea-b755-0fd713f6b65e",
    ),  # Pacific Bakery
    (
        "3a189c4e-83f2-4364-b474-2da9403d3e19",
        "76ec8dd0-20cf-44c0-bdb7-1bc446ce4366",
    ),  # NZ Starch
    (
        "8e1baf74-a1c3-43be-b452-94d211e82401",
        "7c2bdd26-7135-48a8-a5aa-1b8fbddbf8c5",
    ),  # LT McGuinness
    (
        "511e3350-a2e2-4d9e-b971-5e02fe922dda",
        "7050c890-8f6e-454f-be9d-d482d1f4270b",
    ),  # IPL Maintenance
    (
        "226e9630-b770-4e99-93ea-9d4c3f4fa021",
        "7317d696-5090-413b-a756-994c17b3c54e",
    ),  # Eden Park Panel & Paint
    (
        "74deb0d4-5a75-4fd4-abd0-85c716abece2",
        "75f7972e-4aa2-407a-b5bd-28304c67f6e8",
    ),  # Garry Lawrence Roofing
    (
        "7abbce8d-5ff0-4fdd-8732-ca5ff258aa9e",
        "a3fe8b47-2cca-4787-8e2d-9713f16703f8",
    ),  # Gus Kanji
    (
        "eb7f98bc-06eb-47c9-99a0-b973e7fc6137",
        "9c8adc9c-7593-4bac-bbbb-f4a5efe95c06",
    ),  # Irving
    (
        "dea6f7dd-8c8f-47b4-b883-532a009ab11e",
        "ca3f2cda-b146-4111-868a-893f6ba170ff",
    ),  # Free Co Flooring
    (
        "a4b93d24-ca61-4278-8bf7-92ad4523107b",
        "a7276a52-09d3-4143-8d7e-7f6f6e716954",
    ),  # Jenny Stevens
    (
        "40e672c4-7332-4eb9-927f-813c20874d43",
        "ada10565-b1ab-43e3-b0ac-79f2128ceea9",
    ),  # Jerry Friar
    (
        "748550d5-4425-4853-b00b-b6e590e3403b",
        "e556eab0-0621-4483-82f2-05f116597830",
    ),  # Wakefield Metals
    (
        "0c82cbcc-2189-4869-8cb7-3e4168fe97b9",
        "f3539c8f-c4eb-4730-bb9a-0e7e468be9a5",
    ),  # High Mark Foods
    (
        "07063260-78ad-4e55-8aba-5854b0dc1e95",
        "75511302-3ec3-4508-bc02-9f1eadf71fb8",
    ),  # Jack Lum
    (
        "249670e0-27a2-4605-a68f-7eac229a6854",
        "356b8de2-62be-419a-ac0b-a813c53b0244",
    ),  # Nick Hansen
    (
        "34448f75-ed3e-4ba3-b948-7a2d768a1dad",
        "cf57a6f9-53b8-4f5a-8eda-435b4d6fb81e",
    ),  # Rem Wadeh
    (
        "7376ed99-6e39-44cc-af00-a785aef0f998",
        "81475c76-3be9-4c9e-9f74-15e7d232506d",
    ),  # Proclimb
    (
        "4178688e-3111-47f7-b155-e13409bb55e4",
        "a7c282e9-da5a-46a8-900d-315a2e17557f",
    ),  # Stephen Carr
    (
        "ac2b0365-3069-4c90-940b-2dd56fdbb6ac",
        "a7c282e9-da5a-46a8-900d-315a2e17557f",
    ),  # Stephen Carr
    (
        "6132ee9a-47fa-4755-93fb-28d054db2744",
        "42d138e8-33fe-4a88-bc06-36cea6975385",
    ),  # McAlpine Hussmann
    (
        "1628ea3b-72c4-4dfc-b5bd-ac5b57855cce",
        "7ad6022b-0b09-49e4-92ee-8fa4124f86de",
    ),  # Wolfgang
    (
        "f93353fb-be09-4b98-a2a1-7035017e5ba2",
        "501c9415-1e34-444b-91a2-b722f28a6fdb",
    ),  # Bronwyn Jackson
    (
        "1c95b84b-dae0-4ace-8ece-329209278264",
        "730034a7-04f8-4c23-8c42-d8dd49408d1a",
    ),  # Dave Booth
    (
        "b51bf289-cc6d-4137-87e3-0941166bd5a0",
        "49954c00-0d80-4deb-845f-a52c69373fbe",
    ),  # Davison Construction
    (
        "e747a5e0-746b-4f25-9f09-d70044f3c23f",
        "82eb2fc3-3e80-4c92-90c5-6bfe92f4874a",
    ),  # Mike Loomb
    (
        "f66dc794-fa95-442e-8475-f8667512bb81",
        "1785e8e6-2e51-49d8-9c5d-2221359bc2d0",
    ),  # Pete Pederson
    (
        "7c81c774-d986-4ee7-bab1-ca83025bee43",
        "caed8f25-a71c-4053-878e-301cedb8179f",
    ),  # Rick Van Swet
    (
        "dcdca54c-f588-4991-b3fd-a6317b3ba39b",
        "c7332cbf-8e19-4bd6-8b72-00ecba0074b4",
    ),  # Steve Kirby
    (
        "d7c2aec4-5dbb-4f84-a4a5-a7a5f5ef9843",
        "d0868ba1-61a8-4299-ae72-5d36e5d3d6f9",
    ),  # Lindsay Building Services
    (
        "161b2430-db80-4a58-a3d5-a7ffb62c887b",
        "8ed26fa1-73fd-4c68-a63a-e6423afc3e3b",
    ),  # PB Traffic
    (
        "d998e463-d3db-45d4-8a53-3fd08ab09c53",
        "23f54e9d-bea3-4d14-bf8f-0dec2be589b8",
    ),  # NZ Crane
    (
        "1a99b409-e72c-46c5-8ee9-fe7f279699ce",
        "c7efc131-a29d-42e7-a6bd-cb00986d56d9",
    ),  # Dunninghams
    (
        "3882c364-bae8-45cd-a658-85d691b6a108",
        "e4af558d-b510-42af-b152-935cd426d4a9",
    ),  # CGO Corporate
    (
        "9abdef63-da4c-4a2b-9cf0-4b7a4db91adc",
        "6177173a-8499-45a3-8aec-03c707aa8ac5",
    ),  # Watercone
    (
        "f9976610-8a0a-4ac1-8298-30c9f3f19254",
        "b66ac775-90d5-45b3-9a0b-8d89590f59a5",
    ),  # HTS Group
)

# Manually reviewed bridges not covered by exact/nickname name compatibility.
# IDs are legacy contact IDs, retained as CompanyPersonLink IDs by migration 0005.
REVIEWED_PERSON_LINK_EDGES: tuple[PersonLinkEdge, ...] = (
    (
        "90650519-eccd-4766-b869-c3b6e70855f6",
        "df371ed0-43f3-43e1-af59-d5e400e01bed",
    ),  # ?? / Michael Chee
    (
        "13546f44-681c-423d-9e02-abe933f5d8bb",
        "9e50a9b9-8080-4975-a897-3aebc214ab8f",
    ),  # Aaron / Aarron
    (
        "7e6cb791-a308-42ec-9156-889e62ebc52d",
        "8d59aa42-0f30-4669-81b9-ef01753a357e",
    ),  # Arno surname typo
    (
        "05816a5f-38d8-47fc-b3e5-95b3350b058e",
        "79d8d9b2-5b1f-49a1-95ff-9c597ee6888f",
    ),  # Aaron / Arron
    (
        "7e5b48fa-f9e9-46d2-847a-40b3b827f34a",
        "bff2f883-853c-4e7e-b1f8-443a5c24bee4",
    ),  # Bronwyn
    (
        "155c2987-ae6f-4175-9a37-d6ec5f9e3d3b",
        "81f90c08-069b-41e0-9560-afbfc070b945",
    ),  # Cushman Chris
    (
        "6bea2a11-081b-46c3-b3fa-a97e6569aebc",
        "ec2907c6-f932-4b49-862c-e9f5278028cc",
    ),  # Craig typo
    (
        "4663652a-11a9-4fdc-953b-713878be13a1",
        "49b58609-8daa-414a-8654-a64bdacf2f20",
    ),  # Cushman Nave
    (
        "49b58609-8daa-414a-8654-a64bdacf2f20",
        "56172bb3-eb13-4065-8976-c2ef62a08ffe",
    ),  # Cushman Nave job label
    (
        "347ad57f-21ed-405c-89f5-39dd4db6ad03",
        "3598fc0b-da47-4090-8710-df8df78575ab",
    ),  # Dave Yanala typo
    (
        "3c26bb57-3f52-435d-b075-636989e67735",
        "ece95901-35d3-479f-bbad-76d5322dc29a",
    ),  # Edwin typo
    (
        "cbe6808f-5cd5-4c8c-a741-ddc5fd435bd3",
        "df32f23a-1acf-4ab3-bae3-19b034c84db4",
    ),  # malformed Expac name / Rob
    (
        "1c25b5f3-132f-4a67-8b2b-3a9fbdf119ec",
        "5f2f1c93-e0e3-48f6-80c1-6109105e7858",
    ),  # Ian / Iain
    (
        "6d851c6e-6f1c-4966-aa7c-cbc8e495504d",
        "f7a78661-4b9c-42b1-8f7e-39ce162d2848",
    ),  # Joseph typo
    (
        "53a5c735-c00a-42bc-87b4-8cba3635aaa3",
        "e5cc3937-ce4b-45c2-9233-17fe4b2d93cf",
    ),  # John Laycock / Blacklock
    (
        "e782a08c-2e8f-4ff9-b055-3dd3df714ac3",
        "fc30d89f-1038-4f01-9848-9172ce78b88c",
    ),  # Lars typo
    (
        "268461ee-6d32-4a93-9561-d52496cd8492",
        "99ef5e54-8cfb-45ec-ae97-7dcd6d4f37a6",
    ),  # Lee / Jeanette malformed name
    (
        "6950a05e-2219-438d-9021-5203d3b5cb0f",
        "766cf006-4679-4ceb-8971-5be5847aa1cd",
    ),  # Madi
    (
        "13342c5e-225e-4b12-a4c7-8c37b37783a3",
        "3354d901-f860-4411-a290-b34ee28ead3f",
    ),  # Matthew surname typo
    (
        "36200504-e009-47d7-9dde-9db3cbb6f3dc",
        "b64f3614-69fd-4c0a-bb9e-333a6ce35feb",
    ),  # Matt Green repair
    (
        "3a880441-9fdb-4979-b574-ad8e14e39e41",
        "b64f3614-69fd-4c0a-bb9e-333a6ce35feb",
    ),  # Matt Green
    (
        "b13ee247-a890-44ae-8126-1781e78d2375",
        "b64f3614-69fd-4c0a-bb9e-333a6ce35feb",
    ),  # Matt Green
    (
        "4663652a-11a9-4fdc-953b-713878be13a1",
        "9418ddb0-28fd-4def-88d2-d933de154902",
    ),  # Nave / Nav
    (
        "05a82448-d03c-437e-9f88-7bfd1f4d182b",
        "c2f89cdb-109f-4440-bf61-888f927a4c16",
    ),  # Onkar typo
    (
        "c2f89cdb-109f-4440-bf61-888f927a4c16",
        "e19f00a9-2589-4465-a31f-2a2fe566af76",
    ),  # Onkar company variant
    (
        "96241f46-590f-4f3a-a82d-ce3a1c31a260",
        "e0a47879-41d3-48ef-8e68-ebd67c018711",
    ),  # Pederson / Pedersen
    (
        "6913ce62-67e2-4dd1-a0a6-eca0c3cb35d8",
        "8a2de35f-4828-4464-a9e0-44f94ee4e544",
    ),  # Peter / Pieter Badenhorst
    (
        "3abf4238-63ba-4362-8a4d-d22dd6d77496",
        "ec160e6f-7708-43f9-824b-3c219ca4d962",
    ),  # Robbie / Robert Grant
    (
        "44e28e0a-3c70-4ce3-8cff-177f71efd468",
        "c195f5e4-feb8-40ad-8a03-369830607f51",
    ),  # Vimlesh surname typo
)

MATT_GREEN_LINK_ID = UUID("36200504-e009-47d7-9dde-9db3cbb6f3dc")
MATT_WRONG_METHOD_VALUES = {"j.green@northlandroofs.com", "+64277003221"}


def _components(edges: Iterable[tuple[UUID, UUID]]) -> list[set[UUID]]:
    adjacency: dict[UUID, set[UUID]] = defaultdict(set)
    for first_id, second_id in edges:
        adjacency[first_id].add(second_id)
        adjacency[second_id].add(first_id)

    components: list[set[UUID]] = []
    visited: set[UUID] = set()
    for root_id in sorted(adjacency, key=str):
        if root_id in visited:
            continue
        component: set[UUID] = set()
        pending = [root_id]
        while pending:
            person_id = pending.pop()
            if person_id in component:
                continue
            component.add(person_id)
            pending.extend(adjacency[person_id])
        visited.update(component)
        components.append(component)
    return components


def _person_rank(person: Person) -> tuple[bool, int, int, object, str]:
    from apps.crm.models import PhoneCallRecord
    from apps.job.models import Job

    activity = (
        Job.objects.filter(person=person).count()
        + PhoneCallRecord.objects.filter(person=person).count()
    )
    references = person.company_links.count() + person.contact_methods.count()
    return (
        not person.is_active,
        -activity,
        -references,
        person.created_at,
        str(person.id),
    )


def _merge_person_components(components: Iterable[set[UUID]], staff: Staff) -> int:
    merge_count = 0
    for component in components:
        people = list(Person.objects.filter(id__in=component))
        if len(people) < 2:
            continue
        destination = min(people, key=_person_rank)
        for source in sorted(people, key=lambda person: str(person.id)):
            if source.id == destination.id:
                continue
            merge_people(source.id, destination.id, staff)
            merge_count += 1
    return merge_count


def _reviewed_person_components() -> list[set[UUID]]:
    raw_edges = [
        (UUID(first_id), UUID(second_id))
        for first_id, second_id in REVIEWED_PERSON_LINK_EDGES
    ]
    link_ids = {link_id for edge in raw_edges for link_id in edge}
    person_by_link = dict(
        CompanyPersonLink.objects.filter(id__in=link_ids).values_list("id", "person_id")
    )
    active_edges: list[tuple[UUID, UUID]] = []
    for first_link_id, second_link_id in raw_edges:
        first_person_id = person_by_link.get(first_link_id)
        second_person_id = person_by_link.get(second_link_id)
        if first_person_id is None and second_person_id is None:
            continue
        if first_person_id is None or second_person_id is None:
            raise RuntimeError(
                "KAN-278 Person merge evidence is incomplete: "
                f"{first_link_id}, {second_link_id}"
            )
        active_edges.append((first_person_id, second_person_id))
    return _components(active_edges)


def _merge_detected_company_groups(staff: Staff) -> int:
    report = DuplicateIdentityReportService().get_report()
    merge_count = 0
    for group in report["company_groups"]:
        if group["recommendation"] != "merge":
            continue
        canonical_id = group["canonical_id"]
        if canonical_id is None:
            raise RuntimeError(f"Merge group {group['group_id']} has no canonical")
        destination_id = UUID(canonical_id)
        for member in group["members"]:
            source_id = UUID(member["company_id"])
            if source_id == destination_id:
                continue
            merge_companies(source_id, destination_id, staff)
            merge_count += 1
    return merge_count


def _merge_detected_person_groups(staff: Staff) -> int:
    report = DuplicateIdentityReportService().get_report()
    merge_count = 0
    for group in report["person_groups"]:
        if group["recommendation"] != "merge":
            continue
        canonical_id = group["canonical_id"]
        if canonical_id is None:
            raise RuntimeError(f"Merge group {group['group_id']} has no canonical")
        destination_id = UUID(canonical_id)
        for member in group["members"]:
            source_id = UUID(member["person_id"])
            if source_id == destination_id:
                continue
            merge_people(source_id, destination_id, staff)
            merge_count += 1
    return merge_count


def apply_reviewed_duplicate_cleanup() -> tuple[int, int]:
    """Apply the reviewed Company-first then Person cleanup plan."""
    company_pairs = [
        (UUID(source_id), UUID(destination_id))
        for source_id, destination_id in REVIEWED_COMPANY_MERGES
    ]
    company_ids = {company_id for pair in company_pairs for company_id in pair}
    existing_company_ids = set(
        Company.objects.filter(id__in=company_ids).values_list("id", flat=True)
    )
    if not existing_company_ids:
        return 0, 0

    staff = Staff.get_automation_user()
    existing_merges = list(
        Company.objects.filter(
            merged_into__isnull=False,
            merged_into__merged_into__isnull=True,
        ).values_list("id", "merged_into_id")
    )
    for source_id, destination_id in existing_merges:
        if destination_id is None:
            raise RuntimeError(f"Merged Company {source_id} has no destination")
        merge_companies(source_id, destination_id, staff)

    company_merge_count = 0
    for source_id, destination_id in company_pairs:
        source_exists = source_id in existing_company_ids
        destination_exists = destination_id in existing_company_ids
        if not source_exists and not destination_exists:
            continue
        if not source_exists or not destination_exists:
            raise RuntimeError(
                "KAN-278 Company merge evidence is incomplete: "
                f"{source_id}, {destination_id}"
            )
        merge_companies(source_id, destination_id, staff)
        company_merge_count += 1

    matt_link = CompanyPersonLink.objects.filter(id=MATT_GREEN_LINK_ID).first()
    if matt_link is not None:
        ContactMethod.objects.filter(
            person_id=matt_link.person_id,
            normalized_value__in=MATT_WRONG_METHOD_VALUES,
        ).delete()
        Person.objects.filter(id=matt_link.person_id).update(email=None)

    person_merge_count = _merge_person_components(_reviewed_person_components(), staff)
    for _iteration in range(10):
        detected_companies = _merge_detected_company_groups(staff)
        detected_people = _merge_detected_person_groups(staff)
        company_merge_count += detected_companies
        person_merge_count += detected_people
        if detected_companies == 0 and detected_people == 0:
            break
    else:
        raise RuntimeError("KAN-278 cleanup did not converge after 10 iterations")

    remaining = DuplicateIdentityReportService().get_report()["summary"]
    remaining_automatic = (
        remaining["company_merge_groups"] + remaining["person_merge_groups"]
    )
    if remaining_automatic:
        raise RuntimeError(
            f"KAN-278 cleanup left {remaining_automatic} automatic merge groups"
        )
    return company_merge_count, person_merge_count
