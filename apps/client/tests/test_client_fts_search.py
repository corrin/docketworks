"""Python-owned client-name search regression coverage.

Postgres may narrow candidates for performance, but Python owns final matching
and ordering. These tests pin the user-facing behavior, including prefix
matching, false-positive control, and telemetry.
"""

import json
import logging

import pytest
from django.test import RequestFactory
from django.utils import timezone

from apps.client.models import Client
from apps.client.services.client_rest_service import ClientRestService
from apps.workflow.models import SearchTelemetryEvent


def _make_client(name: str, **overrides):
    defaults = {
        "name": name,
        "xero_last_modified": timezone.now(),
        "allow_jobs": True,
    }
    defaults.update(overrides)
    return Client.objects.create(**defaults)


def _make_search_noise_clients(count: int = 2000):
    """
    Client search bugs hide in tiny fixtures: a candidate filter that admits
    substring false positives can still look correct until real matches are
    buried under production-sized noise.
    """
    now = timezone.now()
    clients = []
    for index in range(count):
        if index % 5 == 0:
            name = f"AlphaFume Noise Client {index:04d}"
        elif index % 5 == 1:
            name = f"Smartin Redwood Client {index:04d}"
        else:
            name = f"Noise Client {index:04d}"

        clients.append(
            Client(
                name=name,
                xero_last_modified=now,
                allow_jobs=True,
            )
        )

    Client.objects.bulk_create(clients)


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


def test_partial_name_query_matches_business_name_prefix(db):
    """Production regression: `FUME` must find `Fumecare Ltd`."""
    _make_search_noise_clients()
    _make_client("Fumecare Ltd")
    _make_client("Acme Co")

    result = ClientRestService.list_clients(query="FUME", page=1, page_size=10)
    names = [c["name"] for c in result["results"]]

    assert names == ["Fumecare Ltd"]
    assert result["count"] == 1


def test_full_name_token_query_still_matches_business_name(db):
    """Catches the direct-name branch breaking normal full-token lookup."""
    _make_client("Fumecare Ltd")

    result = ClientRestService.list_clients(query="Fumecare", page=1, page_size=10)
    names = [c["name"] for c in result["results"]]

    assert names == ["Fumecare Ltd"]


def test_prefix_token_score_beats_internal_substring_score(db):
    """`FUME` is a stronger signal for Fumecare than internal `umec`."""
    tokens = ClientRestService._client_search_tokens("FUME")
    internal_tokens = ClientRestService._client_search_tokens("umec")

    assert ClientRestService._client_name_score(
        "Fumecare Ltd", "FUME", tokens
    ) < ClientRestService._client_name_score("Fumecare Ltd", "umec", internal_tokens)


def test_prefix_name_match_ranks_above_internal_substring_match(db):
    """A name-leading token prefix outranks a later token prefix."""
    _make_client("Fumecare Ltd")
    _make_client("Safe Fume Handling")
    _make_client("Acme Co")

    result = ClientRestService.list_clients(query="FUME", page=1, page_size=10)
    names = [c["name"] for c in result["results"]]

    assert names == ["Fumecare Ltd", "Safe Fume Handling"]


def test_internal_substring_does_not_match_business_name(db):
    """`car` inside `Fumecare` is not a token-prefix business-name match."""
    _make_client("Fumecare Ltd")
    _make_client("Carters Tools")

    result = ClientRestService.list_clients(query="car", page=1, page_size=10)
    names = [c["name"] for c in result["results"]]

    assert names == ["Carters Tools"]


def test_internal_fumecare_substring_does_not_match(db):
    """`umec` should score worse than `FUME` and should not be included."""
    _make_client("Fumecare Ltd")

    result = ClientRestService.list_clients(query="umec", page=1, page_size=10)

    assert result["results"] == []
    assert result["count"] == 0


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
    _make_search_noise_clients()
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


def test_search_clients_matches_partial_business_name(db):
    """Top-N client lookup uses the same Python-owned name search."""
    _make_client("Fumecare Ltd")
    _make_client("Acme Co")

    results = ClientRestService.search_clients("FUME", limit=10)
    names = [r["name"] for r in results]

    assert names == ["Fumecare Ltd"]


def test_candidate_filter_is_superset_of_python_name_matching(db):
    """Postgres candidate filtering must not decide final search semantics."""
    clients = [
        _make_client("Fumecare Ltd"),
        _make_client("Hynds Pipe Systems"),
        _make_client("Pipe Hynds Systems"),
        _make_client("Acme Co"),
    ]
    tokens = ClientRestService._client_search_tokens("Hynds Systems")

    candidate_ids = set(
        Client.objects.filter(
            ClientRestService._client_name_candidate_filter(tokens)
        ).values_list("id", flat=True)
    )
    python_ids = {
        client.id
        for client in clients
        if ClientRestService._client_name_matches(client.name, tokens)
    }

    assert python_ids <= candidate_ids


def test_client_search_logging_emits_structured_json(db, caplog):
    """Catches search telemetry drifting from the Kanban logging style."""
    client = _make_client("Fumecare Ltd")
    result = ClientRestService.list_clients(query="FUME", page=1, page_size=10)
    request = RequestFactory().get("/api/clients/search/", {"q": "FUME"})
    request.user = None

    assert result["count"] == 1
    assert result["results"][0]["id"] == str(client.id)

    with caplog.at_level(logging.INFO, logger="client_search"):
        ClientRestService.log_client_search_results(
            request=request,
            source="client_search",
            query="FUME",
            clients=result["results"],
            total_count=result["count"],
        )

    payload = json.loads(caplog.records[0].message)

    assert payload["event"] == "client_search_results"
    assert payload["query"] == "FUME"
    assert payload["query_string"] == "q=FUME"
    assert payload["result_count"] == 1
    assert payload["returned_count"] == 1
    assert payload["results"][0]["rank"] == 1
    assert payload["results"][0]["client_id"] == str(client.id)
    assert payload["results"][0]["client_name"] == "Fumecare Ltd"
    assert payload["results"][0]["search_reasons"][0]["reason"] == "token_prefix"

    event = SearchTelemetryEvent.objects.get(
        event_type=SearchTelemetryEvent.EventType.SEARCH,
        domain=SearchTelemetryEvent.Domain.CLIENT,
    )
    assert event.query == "FUME"
    assert event.normalized_query == "fume"
    assert event.result_count == 1
    assert event.returned_result_ids == [str(client.id)]


def test_search_clients_short_query_is_rejected(db):
    """The 3-character minimum-query guard returns [] without raising."""
    assert ClientRestService.search_clients("ab", limit=10) == []
    assert ClientRestService.search_clients("", limit=10) == []
