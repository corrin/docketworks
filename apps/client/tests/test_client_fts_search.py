"""Postgres FTS regression coverage for client search (Trello #150).

The reported bug: searching `"Hynds Systems"` returned no results because
`name__icontains` matched the query as a contiguous substring against
`"Hynds Pipe Systems"`. This test pins the new Postgres FTS behaviour: token
order is irrelevant, exact phrase matches outrank scattered-token matches,
and quoted phrases use `websearch` syntax.
"""

import pytest
from django.utils import timezone

from apps.client.models import Client
from apps.client.services.client_rest_service import ClientRestService


def _make_client(name: str, **overrides):
    defaults = {
        "name": name,
        "xero_last_modified": timezone.now(),
        "allow_jobs": True,
    }
    defaults.update(overrides)
    return Client.objects.create(**defaults)


@pytest.fixture
def hynds(db):
    return _make_client("Hynds Pipe Systems")


@pytest.fixture
def dog_food(db):
    return _make_client("Acme Dog Food Ltd")


@pytest.fixture
def food_dog(db):
    return _make_client("Food Dog Imports")


def test_multi_token_query_matches_in_any_order(hynds):
    """The Hynds-Pipe-Systems case: tokens in any order must match."""
    result = ClientRestService.list_clients(query="Hynds Systems", page=1, page_size=10)
    names = [c["name"] for c in result["results"]]
    assert "Hynds Pipe Systems" in names


def test_quoted_phrase_outranks_scattered_tokens(dog_food, food_dog):
    """Quoted "Dog Food" must rank the contiguous-phrase row first."""
    result = ClientRestService.list_clients(query='"Dog Food"', page=1, page_size=10)
    names = [c["name"] for c in result["results"]]
    assert names[0] == "Acme Dog Food Ltd"


def test_unquoted_tokens_match_both_orders(dog_food, food_dog):
    """Unquoted `dog food` matches both orderings (AND semantics)."""
    result = ClientRestService.list_clients(query="dog food", page=1, page_size=10)
    names = {c["name"] for c in result["results"]}
    assert names == {"Acme Dog Food Ltd", "Food Dog Imports"}


def test_single_token_query_matches(hynds):
    """If single-token FTS breaks, the most common search pattern (typing
    one word into the search box) silently returns nothing — every user
    experiences a broken search.
    """
    result = ClientRestService.list_clients(query="Hynds", page=1, page_size=10)
    names = [c["name"] for c in result["results"]]
    assert "Hynds Pipe Systems" in names


def test_no_match_returns_empty(db):
    """
    Regression: the filter must use the `@@` match operator, not
    `search_rank__gt=0`. Postgres' `ts_rank` returns a ~1e-20 epsilon for
    non-matching documents, so a `gt=0` filter returns every row in the
    table — which masquerades as an empty no-match path during unit tests
    but corrupts ranking in production by burying real matches under
    thousands of fake ones.
    """
    _make_client("Acme Co")
    result = ClientRestService.list_clients(
        query="zzzqqxnonsense", page=1, page_size=10
    )
    assert result["results"] == []
    assert result["count"] == 0


def test_martin_wood_against_compound_name(db):
    """
    Regression for the user-reported `Martin Wood` → `Martin, Price and Wood`
    case. The english config strips `and` as a stop word, so the indexed
    lexemes are {martin, price, wood}; the websearch query becomes
    `martin & wood` which should match. This test fails if the buggy
    `search_rank__gt=0` filter is reintroduced (because junk-rank rows
    sort above genuine matches once results are paginated).
    """
    _make_client("Martin, Price and Wood")
    _make_client("Wood, Martin and Calhoun")
    _make_client("Smith Co")
    _make_client("Walton and Sons")

    result = ClientRestService.list_clients(query="Martin Wood", page=1, page_size=10)
    names = [c["name"] for c in result["results"]]
    assert "Martin, Price and Wood" in names
    assert "Wood, Martin and Calhoun" in names
    assert "Smith Co" not in names
    assert "Walton and Sons" not in names


def test_search_clients_top_n_respects_allow_jobs(db):
    """search_clients() requires allow_jobs=True (job-eligible only)."""
    _make_client("Acme Foo", allow_jobs=True)
    _make_client("Acme Bar", allow_jobs=False)

    results = ClientRestService.search_clients("Acme", limit=10)
    names = [r["name"] for r in results]
    assert "Acme Foo" in names
    assert "Acme Bar" not in names


def test_search_clients_short_query_is_rejected(db):
    """The 3-character minimum-query guard returns [] without raising."""
    assert ClientRestService.search_clients("ab", limit=10) == []
    assert ClientRestService.search_clients("", limit=10) == []
