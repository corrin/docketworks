"""Coherent fake staff profiles for the production-dump scrubber.

Ported from v1's ``apps/accounts/staff_anonymization.py``; it lives in
diagnostics rather than accounts because the scrubber is its only consumer.
Curated profiles instead of plain Faker names on purpose: preferred_name and
the email local-part stay coherent with first_name, so a scrubbed database
still reads like a real staff list.
"""

import random
from typing import TypedDict


class _NameProfile(TypedDict):
    first: str
    preferred: str
    email_style: str


class StaffProfile(TypedDict):
    """One generated staff identity: names plus a matching email address."""

    first_name: str
    last_name: str
    preferred_name: str | None
    email: str


# Diverse name profiles where preferred_name and email are coherent with first_name
NAME_PROFILES: list[_NameProfile] = [
    # Western names with common nicknames
    {"first": "William", "preferred": "Bill", "email_style": "nickname"},
    {"first": "Michael", "preferred": "Mike", "email_style": "first"},
    {"first": "Elizabeth", "preferred": "Liz", "email_style": "nickname"},
    {"first": "Robert", "preferred": "Bob", "email_style": "first"},
    {"first": "Katherine", "preferred": "Kate", "email_style": "initial"},
    {"first": "Christopher", "preferred": "Chris", "email_style": "nickname"},
    {"first": "Jennifer", "preferred": "Jen", "email_style": "first"},
    {"first": "Anthony", "preferred": "Tony", "email_style": "unrelated"},
    {"first": "Richard", "preferred": "Dick", "email_style": "first"},
    {"first": "Margaret", "preferred": "Maggie", "email_style": "nickname"},
    {"first": "Thomas", "preferred": "Tom", "email_style": "first"},
    {"first": "Patricia", "preferred": "Pat", "email_style": "initial"},
    {"first": "Joseph", "preferred": "Joe", "email_style": "nickname"},
    {"first": "Rebecca", "preferred": "Bec", "email_style": "first"},
    {"first": "Alexander", "preferred": "Alex", "email_style": "nickname"},
    {"first": "Victoria", "preferred": "Vicky", "email_style": "first"},
    {"first": "Benjamin", "preferred": "Ben", "email_style": "first"},
    {"first": "Samantha", "preferred": "Sam", "email_style": "nickname"},
    {"first": "Nicholas", "preferred": "Nick", "email_style": "first"},
    {"first": "Stephanie", "preferred": "Steph", "email_style": "initial"},
    {"first": "Timothy", "preferred": "Tim", "email_style": "first"},
    {"first": "Christina", "preferred": "Tina", "email_style": "nickname"},
    {"first": "Matthew", "preferred": "Matt", "email_style": "first"},
    {"first": "Deborah", "preferred": "Deb", "email_style": "first"},
    {"first": "Jonathan", "preferred": "Jon", "email_style": "nickname"},
    {"first": "Jacqueline", "preferred": "Jackie", "email_style": "first"},
    {"first": "Theodore", "preferred": "Ted", "email_style": "unrelated"},
    {"first": "Catherine", "preferred": "Cathy", "email_style": "nickname"},
    {"first": "Nathaniel", "preferred": "Nate", "email_style": "first"},
    {"first": "Gabrielle", "preferred": "Gabby", "email_style": "initial"},
    # Asian names with Western preferred names
    {"first": "Wei", "preferred": "William", "email_style": "preferred"},
    {"first": "Xiaoming", "preferred": "Simon", "email_style": "preferred"},
    {"first": "Mei-Lin", "preferred": "Emily", "email_style": "preferred"},
    {"first": "Hiroshi", "preferred": "Harry", "email_style": "first"},
    {"first": "Priya", "preferred": "Priya", "email_style": "first"},
    {"first": "Raj", "preferred": "Roger", "email_style": "preferred"},
    {"first": "Yuki", "preferred": "Julia", "email_style": "preferred"},
    {"first": "Kenji", "preferred": "Kenny", "email_style": "preferred"},
    {"first": "Li", "preferred": "Lee", "email_style": "first"},
    {"first": "Chen", "preferred": "Charlie", "email_style": "preferred"},
    {"first": "Anh", "preferred": "Anna", "email_style": "preferred"},
    {"first": "Minh", "preferred": "Michael", "email_style": "preferred"},
    {"first": "Sanjay", "preferred": "Sam", "email_style": "preferred"},
    {"first": "Deepak", "preferred": "Dave", "email_style": "preferred"},
    {"first": "Arjun", "preferred": "AJ", "email_style": "initial"},
    {"first": "Kavitha", "preferred": "Kavi", "email_style": "first"},
    # Names where preferred = first (no nickname needed)
    {"first": "David", "preferred": "David", "email_style": "first"},
    {"first": "Sarah", "preferred": "Sarah", "email_style": "initial"},
    {"first": "James", "preferred": "James", "email_style": "first"},
    {"first": "Emma", "preferred": "Emma", "email_style": "first"},
    {"first": "Daniel", "preferred": "Daniel", "email_style": "unrelated"},
    {"first": "Sophie", "preferred": "Sophie", "email_style": "first"},
    {"first": "Ryan", "preferred": "Ryan", "email_style": "first"},
    {"first": "Grace", "preferred": "Grace", "email_style": "initial"},
    {"first": "Luke", "preferred": "Luke", "email_style": "first"},
    {"first": "Olivia", "preferred": "Olivia", "email_style": "first"},
    {"first": "Jack", "preferred": "Jack", "email_style": "first"},
    {"first": "Chloe", "preferred": "Chloe", "email_style": "unrelated"},
    {"first": "Ethan", "preferred": "Ethan", "email_style": "first"},
    {"first": "Mia", "preferred": "Mia", "email_style": "first"},
]

LAST_NAMES = [
    "Smith",
    "Johnson",
    "Williams",
    "Brown",
    "Jones",
    "Garcia",
    "Miller",
    "Davis",
    "Wilson",
    "Taylor",
    "Chen",
    "Wang",
    "Kim",
    "Nguyen",
    "Singh",
    "Patel",
    "O'Brien",
    "McDonald",
    "Van Der Berg",
    "De Santos",
    "Thompson",
    "White",
    "Harris",
    "Martin",
    "Jackson",
    "Lee",
    "Perez",
    "Clark",
    "Lewis",
    "Robinson",
    "Walker",
    "Young",
    "Allen",
    "King",
    "Wright",
    "Scott",
    "Torres",
    "Hill",
    "Flores",
    "Green",
    "Adams",
    "Nelson",
    "Baker",
    "Hall",
    "Rivera",
]

UNRELATED_EMAILS = [
    "coolguy",
    "speedracer",
    "sunshine",
    "moonlight",
    "techie",
    "workshopking",
    "metalman",
    "builder",
    "craftsman",
    "maker",
    "steelworker",
    "fabricator",
    "welder",
    "machinist",
    "engineer",
]


def generate_email(profile: _NameProfile, last_name: str) -> str:
    """Generate an @example.com address matching the profile's email_style."""
    style = profile["email_style"]
    last_clean = last_name.lower().replace(" ", "").replace("'", "")

    if style == "first":
        return f"{profile['first'].lower()}.{last_clean}@example.com"
    if style in ("nickname", "preferred"):
        return f"{profile['preferred'].lower()}.{last_clean}@example.com"
    if style == "initial":
        return f"{profile['first'][0].lower()}.{last_clean}@example.com"
    if style == "unrelated":
        return f"{random.choice(UNRELATED_EMAILS)}{random.randint(1, 99)}@example.com"  # noqa: S311 -- fake identities, not secrets
    # v1 fell back to a bare first-name address here; every style in
    # NAME_PROFILES is handled above, so reaching this is a table edit gone
    # wrong and masking it would silently degrade the anonymisation.
    raise ValueError(f"Unknown email_style {style!r} in NAME_PROFILES")


def create_staff_profile() -> StaffProfile:
    """Create a coherent staff profile where preferred_name and email match the name."""
    profile = random.choice(NAME_PROFILES)  # noqa: S311 -- fake identities, not secrets
    last_name = random.choice(LAST_NAMES)  # noqa: S311 -- fake identities, not secrets

    # ~50% of staff don't set a preferred name
    has_preferred = random.random() > 0.5  # noqa: S311 -- fake identities, not secrets

    return {
        "first_name": profile["first"],
        "last_name": last_name,
        "preferred_name": profile["preferred"] if has_preferred else None,
        "email": generate_email(profile, last_name),
    }
