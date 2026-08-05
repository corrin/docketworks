"""Python-owned company-name search regression coverage.

Postgres may narrow candidates for performance, but Python owns final matching
and ordering. These tests pin the user-facing behavior, including prefix
matching and false-positive control.

SearchTelemetryEvent persistence is excluded because domain apps may not
import the search integration. Noise fixtures stay small while preserving the
ranking risks they exercise.
"""

import pytest

from apps.company.models import Company
from apps.company.services.company_rest_service import (
    CompanyRestService,
    CompanySearchPage,
)
from apps.company.tests.conftest import make_company

pytestmark = pytest.mark.django_db


def _names(result: CompanySearchPage) -> list[str]:
    return [c["name"] for c in result["results"]]


def test_multi_token_query_matches_in_any_order() -> None:
    make_company("Hynds Pipe Systems")

    forward = CompanyRestService.list_companies(query="Hynds Pipe", page=1, page_size=10)
    backward = CompanyRestService.list_companies(query="Pipe Hynds", page=1, page_size=10)

    assert "Hynds Pipe Systems" in _names(forward)
    assert "Hynds Pipe Systems" in _names(backward)


def test_quoted_phrase_order_outranks_scattered_tokens() -> None:
    make_company("Acme Dog Food Ltd")
    make_company("Food Dog Imports")

    result = CompanyRestService.list_companies(query="Dog Food", page=1, page_size=10)

    assert _names(result)[0] == "Acme Dog Food Ltd"
    assert set(_names(result)) == {"Acme Dog Food Ltd", "Food Dog Imports"}


def test_single_token_query_matches() -> None:
    make_company("Hynds Pipe Systems")

    result = CompanyRestService.list_companies(query="Hynds", page=1, page_size=10)

    assert "Hynds Pipe Systems" in _names(result)


def test_partial_name_query_matches_business_name_prefix() -> None:
    """Production regression: `FUME` must find `Fumecare Ltd`."""
    make_company("Fumecare Ltd")
    make_company("Acme Co")

    result = CompanyRestService.list_companies(query="FUME", page=1, page_size=10)

    assert _names(result) == ["Fumecare Ltd"]
    assert result["count"] == 1


def test_prefix_token_score_beats_internal_substring_score() -> None:
    """`FUME` is a stronger signal for Fumecare than internal `umec`."""
    tokens = CompanyRestService._company_search_tokens("FUME")
    internal_tokens = CompanyRestService._company_search_tokens("umec")

    assert CompanyRestService._company_name_score(
        "Fumecare Ltd", "FUME", tokens
    ) < CompanyRestService._company_name_score("Fumecare Ltd", "umec", internal_tokens)


def test_prefix_name_match_ranks_above_internal_substring_match() -> None:
    """A name-leading token prefix outranks a later token prefix."""
    make_company("Fumecare Ltd")
    make_company("Safe Fume Handling")
    make_company("Acme Co")

    result = CompanyRestService.list_companies(query="FUME", page=1, page_size=10)

    assert _names(result) == ["Fumecare Ltd", "Safe Fume Handling"]


def test_internal_substring_does_not_match_business_name() -> None:
    """`car` inside `Fumecare` is not a token-prefix business-name match."""
    make_company("Fumecare Ltd")
    make_company("Carters Tools")

    result = CompanyRestService.list_companies(query="car", page=1, page_size=10)

    assert _names(result) == ["Carters Tools"]


def test_internal_fumecare_substring_does_not_match() -> None:
    make_company("Fumecare Ltd")

    result = CompanyRestService.list_companies(query="umec", page=1, page_size=10)

    assert result["results"] == []
    assert result["count"] == 0


def test_no_match_returns_empty() -> None:
    make_company("Acme Co")

    result = CompanyRestService.list_companies(query="zzzqqxnonsense", page=1, page_size=10)

    assert result["results"] == []
    assert result["count"] == 0


def test_martin_wood_against_compound_name() -> None:
    """Regression for the user-reported `Martin Wood` → `Martin, Price and Wood` case."""
    make_company("Martin, Price and Wood")
    make_company("Wood, Martin and Calhoun")
    make_company("Smith Co")
    make_company("Walton and Sons")

    result = CompanyRestService.list_companies(query="Martin Wood", page=1, page_size=10)

    names = _names(result)
    assert "Martin, Price and Wood" in names
    assert "Wood, Martin and Calhoun" in names
    assert "Smith Co" not in names
    assert "Walton and Sons" not in names


def test_search_companies_top_n_respects_allow_jobs() -> None:
    """search_companies() requires allow_jobs=True (job-eligible only)."""
    make_company("Acme Foo", allow_jobs=True)
    make_company("Acme Bar", allow_jobs=False)

    results = CompanyRestService.search_companies("Acme", limit=10)

    names = [r["name"] for r in results]
    assert "Acme Foo" in names
    assert "Acme Bar" not in names


def test_search_companies_matches_partial_business_name() -> None:
    """Top-N company lookup uses the same Python-owned name search."""
    make_company("Fumecare Ltd")
    make_company("Acme Co")

    results = CompanyRestService.search_companies("FUME", limit=10)

    assert [r["name"] for r in results] == ["Fumecare Ltd"]


def test_candidate_filter_is_superset_of_python_name_matching() -> None:
    """Postgres candidate filtering must not decide final search semantics."""
    companies = [
        make_company("Fumecare Ltd"),
        make_company("Hynds Pipe Systems"),
        make_company("Pipe Hynds Systems"),
        make_company("Acme Co"),
    ]
    tokens = CompanyRestService._company_search_tokens("Hynds Systems")

    candidate_ids = set(
        Company.objects.filter(
            CompanyRestService._company_name_candidate_filter(tokens)
        ).values_list("id", flat=True)
    )
    python_ids = {
        company.id
        for company in companies
        if CompanyRestService._company_name_matches(company.name, tokens)
    }

    assert python_ids <= candidate_ids


def test_search_companies_short_query_is_rejected() -> None:
    """The 3-character minimum-query guard returns [] without raising."""
    assert CompanyRestService.search_companies("ab", limit=10) == []
    assert CompanyRestService.search_companies("", limit=10) == []


def test_merged_tombstone_is_excluded_from_browse_and_search() -> None:
    """A merged company's data lives on the winner (ADR 0034); listing the
    tombstone alongside it would show the same business twice."""
    winner = make_company("Tombstone Winner Ltd")
    make_company("Tombstone Loser Ltd", merged_into=winner, allow_jobs=False)

    browsed = CompanyRestService.list_companies(page=1, page_size=50)
    assert "Tombstone Winner Ltd" in _names(browsed)
    assert "Tombstone Loser Ltd" not in _names(browsed)

    searched = CompanyRestService.list_companies(query="Tombstone", page=1, page_size=50)
    assert _names(searched) == ["Tombstone Winner Ltd"]
