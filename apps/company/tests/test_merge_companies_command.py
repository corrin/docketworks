"""Tests for the merge_companies management command (thin wrapper over the service)."""

from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.company.models import Company
from apps.company.tests.conftest import make_company

pytestmark = pytest.mark.django_db


def _run(*args: str) -> str:
    out = StringIO()
    call_command("merge_companies", *args, stdout=out)
    return out.getvalue()


def test_auto_merges_same_named_duplicates_into_oldest() -> None:
    now = timezone.now()
    primary = make_company("Acme Ltd")
    Company.objects.filter(id=primary.id).update(django_created_at=now - timedelta(days=2))
    loser_one = make_company("Acme Ltd", email="dup1@acme.test")
    loser_two = make_company("Acme Ltd", email="dup2@acme.test")

    output = _run("--name", "Acme Ltd", "--auto")

    assert "Found 3 companies" in output
    assert "Success!" in output
    primary.refresh_from_db()
    loser_one.refresh_from_db()
    loser_two.refresh_from_db()
    assert primary.merged_into_id is None
    assert loser_one.merged_into_id == primary.id
    assert loser_two.merged_into_id == primary.id
    assert loser_one.allow_jobs is False
    # Missing scalar fields are absorbed from the first-merged loser.
    assert primary.email == "dup1@acme.test"


def test_single_company_is_a_noop() -> None:
    company = make_company("Solo Ltd")

    output = _run("--name", "Solo Ltd", "--auto")

    assert "no duplicates to fix" in output
    company.refresh_from_db()
    assert company.merged_into_id is None


def test_unknown_name_reports_nothing_found() -> None:
    output = _run("--name", "Nobody Ltd", "--auto")
    assert "No companies found" in output


def test_existing_tombstones_are_not_candidates() -> None:
    winner = make_company("Repeat Ltd")
    tombstone = make_company("Repeat Ltd")
    tombstone.merged_into = winner
    tombstone.save(update_fields=["merged_into"])

    output = _run("--name", "Repeat Ltd", "--auto")

    assert "no duplicates to fix" in output
