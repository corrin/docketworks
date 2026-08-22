"""Attack the outbound-link probe: prove each verdict fires when it should.

Fable: A link gate that has never reported a broken link has never been shown
to detect one. These cases plant the defects the probe exists to catch — a
404 route, a trashed Google file, a branding theme Xero no longer offers —
and assert the verdict, with fakes standing in for the vendor transports
only at the edge the integration test covers for real (ADR 0050).
"""

from __future__ import annotations

import json
import socket
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import httplib2
import pytest
import requests
from googleapiclient.errors import HttpError
from urllib3 import HTTPConnectionPool
from urllib3.connection import HTTPConnection
from urllib3.exceptions import MaxRetryError, NameResolutionError

from apps.core.models import CompanyDefaults

if TYPE_CHECKING:
    from google.oauth2.service_account import Credentials
from scripts.ops.outbound_links_probe import (
    DriveLookup,
    GoogleFileState,
    LinkVerdict,
    NoSuchHostError,
    OutboundLink,
    UnreachableError,
    classify_url,
    enumerate_company_defaults,
    enumerate_database_links,
    enumerate_manifest,
    excluded_reason,
    main,
    requests_fetch,
    scan_source_literals,
    unclassified_fields,
    verify_all,
    verify_google_file,
    verify_http,
    verify_xero,
)


class TestScanSourceLiterals:
    def test_a_planted_literal_is_found_with_its_file_and_line(self, tmp_path: Path) -> None:
        (tmp_path / "apps").mkdir()
        (tmp_path / "apps" / "thing.py").write_text(
            'X = 1\nURL = "https://go.xero.com/Settings/InvoiceSettings/"\n'
        )

        links = scan_source_literals(tmp_path, paths=("apps",))

        assert links == [
            OutboundLink(
                kind="xero_web",
                source="apps/thing.py:2",
                url="https://go.xero.com/Settings/InvoiceSettings/",
            )
        ]

    def test_trailing_punctuation_and_markdown_delimiters_are_not_part_of_the_url(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "a.md").write_text(
            "See [MDN](https://developer.mozilla.org/en-US/docs/Web). "
            "Then https://swagger.io/, ok.\n"
        )

        urls = [link.url for link in scan_source_literals(tmp_path, paths=("docs",))]

        assert urls == ["https://developer.mozilla.org/en-US/docs/Web", "https://swagger.io/"]

    def test_the_same_url_in_two_files_is_probed_once(self, tmp_path: Path) -> None:
        (tmp_path / "apps").mkdir()
        (tmp_path / "apps" / "a.py").write_text('"https://swagger.io/"\n')
        (tmp_path / "apps" / "b.py").write_text('"https://swagger.io/"\n')

        links = scan_source_literals(tmp_path, paths=("apps",))

        assert [link.source for link in links] == ["apps/a.py:1"]

    def test_server_templates_and_nginx_confs_are_scanned(self, tmp_path: Path) -> None:
        (tmp_path / "scripts" / "server" / "templates").mkdir(parents=True)
        (tmp_path / "scripts" / "server" / "templates" / "site.template").write_text(
            "proxy_pass https://www.docketworks.site/;\n"
        )
        (tmp_path / "scripts" / "server" / "base.conf").write_text(
            "# see https://developer.xero.com/app/manage\n"
        )

        urls = sorted(link.url or "" for link in scan_source_literals(tmp_path, paths=("scripts",)))

        assert urls == ["https://developer.xero.com/app/manage", "https://www.docketworks.site/"]

    def test_a_missing_scan_path_fails_loud(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            scan_source_literals(tmp_path, paths=("apps",))

    def test_generated_and_dependency_trees_are_not_scanned(self, tmp_path: Path) -> None:
        (tmp_path / "frontend" / "src" / "api" / "generated").mkdir(parents=True)
        (tmp_path / "frontend" / "src" / "api" / "generated" / "x.ts").write_text(
            '"https://go.xero.com/nope"'
        )
        (tmp_path / "frontend" / "src" / "node_modules").mkdir()
        (tmp_path / "frontend" / "src" / "node_modules" / "y.js").write_text(
            '"https://go.xero.com/nope2"'
        )

        assert scan_source_literals(tmp_path, paths=("frontend/src",)) == []

    def test_test_files_are_fixtures_not_links_and_are_not_scanned(self, tmp_path: Path) -> None:
        (tmp_path / "apps" / "x" / "tests").mkdir(parents=True)
        (tmp_path / "apps" / "x" / "tests" / "test_y.py").write_text('"https://go.xero.com/nope"')
        (tmp_path / "frontend" / "src").mkdir(parents=True)
        (tmp_path / "frontend" / "src" / "Card.test.tsx").write_text('"https://go.xero.com/nope2"')
        (tmp_path / "frontend" / "src" / "card.spec.ts").write_text('"https://go.xero.com/nope3"')

        assert scan_source_literals(tmp_path, paths=("apps", "frontend/src")) == []

    def test_a_host_that_cannot_be_verified_is_a_visible_skip_not_a_silent_omission(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "a.md").write_text("https://docketworks.atlassian.net/browse/KAN-1\n")

        links = scan_source_literals(tmp_path, paths=("docs",))

        assert len(links) == 1
        assert links[0].kind == "skipped"
        assert links[0].url == "https://docketworks.atlassian.net/browse/KAN-1"
        assert "202" in links[0].detail


class TestEnumerateManifest:
    def test_under_the_service_account_the_manifest_is_a_visible_skip(self, tmp_path: Path) -> None:
        manifest = tmp_path / "google_doc_manifest.json"
        manifest.write_text('{"1Doc": {"folder_id": "1Folder", "title": "Overview"}}')

        links = enumerate_manifest(manifest, google_as="service-account")

        assert [(link.kind, link.external_id) for link in links] == [
            ("skipped", "1Doc"),
            ("skipped", "1Folder"),
        ]
        assert "delegated" in links[0].detail

    def test_as_the_delegated_author_the_manifest_is_checked(self, tmp_path: Path) -> None:
        manifest = tmp_path / "google_doc_manifest.json"
        manifest.write_text('{"1Doc": {"folder_id": "1Folder", "title": "Overview"}}')

        links = enumerate_manifest(manifest, google_as="delegated")

        assert [(link.kind, link.external_id) for link in links] == [
            ("google_file", "1Doc"),
            ("google_file", "1Folder"),
        ]


class TestExclusions:
    @pytest.mark.parametrize(
        "url",
        [
            "https://example.test/hook",
            "https://phone.example.test/",
            "https://attacker.example/x",
            "https://example.com/",
            "http://localhost:8000/api/",
            "http://127.0.0.1:4040/api/tunnels",
            "https://x",
            "https://docketworks-dave.ngrok-free.app/",
            "https://acme.docketworks.site/",
            "https://go.xero.com/app/invoicing/edit/{invoice_id}",
            "http://www.w3.org/2000/svg",
            "http://docketworks.invalid",
            "https://$FQDN/api/build-id/",
            "https://$INSTANCE.$DOMAIN",
            "http://unix:/opt/docketworks/instances/test-uat/gunicorn.sock",
            "https://{settings.APP_DOMAIN}/api/xero/oauth/callback/",
            "https://login.xero.com/identity/connect/authorize?{urlencode",
            "https://APP_DOMAIN",
            "https://cli.github.com/packages",
            "https://__INSTANCE__.docketworks.site/api/xero/webhook/",
        ],
    )
    def test_a_deliberate_fake_is_excluded_with_a_reason(self, url: str) -> None:
        reason = excluded_reason(url)

        assert reason is not None
        assert reason

    @pytest.mark.parametrize(
        "url",
        [
            "https://go.xero.com/InvoiceSettings/InvoiceSettings.aspx",
            "https://api.xero.com/api.xro/2.0/",
            "https://developer.mozilla.org/",
            "https://docs.google.com/document/d/abc/edit",
            "https://www.docketworks.site/",
            "https://docketworks.site",
        ],
    )
    def test_a_real_host_is_never_excluded(self, url: str) -> None:
        assert excluded_reason(url) is None


class TestClassifyUrl:
    @pytest.mark.parametrize(
        ("url", "file_id"),
        [
            ("https://docs.google.com/document/d/1AbC-_9/edit", "1AbC-_9"),
            ("https://docs.google.com/spreadsheets/d/1Sheet/edit#gid=0", "1Sheet"),
            ("https://drive.google.com/drive/folders/1Folder?usp=sharing", "1Folder"),
            ("https://drive.google.com/drive/u/0/folders/1Folder2", "1Folder2"),
            ("https://drive.google.com/file/d/1File/view", "1File"),
            ("https://drive.google.com/open?id=1Open", "1Open"),
        ],
    )
    def test_google_document_urls_resolve_to_a_drive_file_id(self, url: str, file_id: str) -> None:
        link = classify_url(url, source="s")

        assert link.kind == "google_file"
        assert link.external_id == file_id

    def test_a_published_google_doc_is_a_plain_http_probe_not_a_drive_id(self) -> None:
        """``/d/e/<token>/pub`` is a publish token, not a file id: anonymous GET is right."""
        link = classify_url("https://docs.google.com/document/d/e/2PACX-1vTabc/pub", source="s")

        assert link.kind == "http"

    @pytest.mark.parametrize("value", ["", "www.morrissheetmetal.co.nz", "mailto:x@y.example"])
    def test_a_value_without_an_http_scheme_is_broken_before_any_network_call(
        self, value: str
    ) -> None:
        """A v1 row without a scheme is a defect in the data, reported, never a traceback."""
        link = classify_url(value, source="s")

        assert link.kind == "broken"
        assert "http" in link.detail

    def test_a_google_host_without_a_file_id_is_a_plain_http_probe(self) -> None:
        assert classify_url("https://developers.google.com/drive", source="s").kind == "http"

    @pytest.mark.parametrize(
        "url",
        [
            "https://go.xero.com/InvoiceSettings/InvoiceSettings.aspx",
            "https://payroll.xero.com/PayRun?CID=x",
        ],
    )
    def test_xero_web_pages_are_route_probes(self, url: str) -> None:
        assert classify_url(url, source="s").kind == "xero_web"

    def test_a_reserved_placeholder_held_as_data_is_a_visible_skip(self) -> None:
        """The seed fixture's company_url (www.democompany.example.com) is a placeholder."""
        link = classify_url(
            "https://www.democompany.example.com", source="CompanyDefaults.company_url"
        )

        assert link.kind == "skipped"
        assert "RFC 2606" in link.detail

    def test_a_post_only_google_api_method_is_a_visible_skip(self) -> None:
        link = classify_url(
            "https://addressvalidation.googleapis.com/v1:validateAddress", source="s"
        )

        assert link.kind == "skipped"
        assert "POST" in link.detail

    def test_anything_else_is_http(self) -> None:
        assert classify_url("https://developer.mozilla.org/", source="s").kind == "http"


def _http(url: str) -> OutboundLink:
    return OutboundLink(kind="http", source="s", url=url)


class TestVerifyHttp:
    def test_a_final_2xx_is_ok(self) -> None:
        assert verify_http(_http("https://a/"), fetch=lambda _url: 200).verdict == "ok"

    def test_a_404_is_broken(self) -> None:
        verdict = verify_http(_http("https://a/"), fetch=lambda _url: 404)

        assert verdict.verdict == "broken"
        assert "404" in verdict.detail

    @pytest.mark.parametrize("status", [400, 401, 403, 405])
    def test_a_server_that_demands_credentials_or_another_method_has_routed_the_url(
        self, status: int
    ) -> None:
        """api.xero.com answers 401 and a POST-only token endpoint answers 400: both exist."""
        verdict = verify_http(_http("https://a/"), fetch=lambda _url: status)

        assert verdict.verdict == "ok"
        assert str(status) in verdict.detail

    def test_a_host_that_does_not_resolve_is_broken_not_unreachable(self) -> None:
        """A deleted domain is the same defect as a deleted doc."""

        def fetch(_url: str) -> int:
            raise NoSuchHostError("www.democompany.example.com")

        verdict = verify_http(_http("https://www.democompany.example.com/"), fetch=fetch)

        assert verdict.verdict == "broken"
        assert "resolve" in verdict.detail

    def test_a_5xx_is_broken(self) -> None:
        assert verify_http(_http("https://a/"), fetch=lambda _url: 503).verdict == "broken"

    def test_a_transport_failure_is_unreachable_not_broken(self) -> None:
        def fetch(_url: str) -> int:
            raise UnreachableError("connection refused")

        verdict = verify_http(_http("https://a/"), fetch=fetch)

        assert verdict.verdict == "unreachable"
        assert "connection refused" in verdict.detail


class _Answer:
    def __init__(self, status: int) -> None:
        self.status_code = status

    def close(self) -> None:
        pass


def _scripted_get(
    monkeypatch: pytest.MonkeyPatch, answers: list[int | Exception]
) -> Callable[[], int]:
    calls = 0

    def fake_get(_url: str, **_kwargs: object) -> _Answer:
        nonlocal calls
        answer = answers[calls]
        calls += 1
        if isinstance(answer, Exception):
            raise answer
        return _Answer(answer)

    monkeypatch.setattr(requests, "get", fake_get)
    return lambda: calls


def _dns_failure(errno: int) -> requests.ConnectionError:
    gai = socket.gaierror(errno, "resolver says no")
    resolution = NameResolutionError("dead.example", HTTPConnection("dead.example"), gai)
    pool = HTTPConnectionPool("dead.example")
    return requests.ConnectionError(MaxRetryError(pool, "https://dead.example/", resolution))


class TestRequestsFetch:
    def test_a_5xx_is_retried_once_and_the_second_answer_wins(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _scripted_get(monkeypatch, [503, 200])

        assert requests_fetch("https://a/") == 200
        assert calls() == 2

    def test_a_persistent_5xx_is_reported_as_that_status(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _scripted_get(monkeypatch, [503, 503])

        assert requests_fetch("https://a/") == 503

    def test_a_4xx_is_not_retried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = _scripted_get(monkeypatch, [404])

        assert requests_fetch("https://a/") == 404
        assert calls() == 1

    def test_rate_limiting_is_the_host_declining_to_answer_not_a_dead_link(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _scripted_get(monkeypatch, [429, 429])

        with pytest.raises(UnreachableError, match="429"):
            requests_fetch("https://a/")

    def test_a_host_that_does_not_exist_is_dead(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _scripted_get(monkeypatch, [_dns_failure(socket.EAI_NONAME)])

        with pytest.raises(NoSuchHostError):
            requests_fetch("https://dead.example/")

    def test_a_resolver_that_is_down_is_unreachable_not_a_dead_host(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """EAI_AGAIN is "try later": offline, every host would otherwise read as deleted."""
        _scripted_get(monkeypatch, [_dns_failure(socket.EAI_AGAIN), _dns_failure(socket.EAI_AGAIN)])

        with pytest.raises(UnreachableError):
            requests_fetch("https://dead.example/")


class _FakeDriveService:
    def __init__(self, outcome: dict[str, object] | Exception) -> None:
        self._outcome = outcome

    def files(self) -> _FakeDriveService:
        return self

    def get(self, **_kwargs: object) -> _FakeDriveService:
        return self

    def execute(self) -> dict[str, object]:
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


def _drive_error(status: int, reason: str) -> HttpError:
    body = json.dumps({"error": {"errors": [{"reason": reason}], "message": reason}}).encode()
    return HttpError(httplib2.Response({"status": str(status)}), body)


def _lookup(outcome: dict[str, object] | Exception) -> DriveLookup:
    class Fake(DriveLookup):
        # Fable: the fake stands in for the discovery resource, which the
        # stubs type as a concrete class rather than a Protocol.
        def drive(self) -> _FakeDriveService:  # type: ignore[override]
            return _FakeDriveService(outcome)

    def never_called() -> Credentials:
        raise AssertionError("the fake never builds credentials")

    return Fake(credentials=never_called)


class TestDriveLookup:
    def test_a_404_is_missing(self) -> None:
        assert _lookup(_drive_error(404, "notFound"))("1a").status == "missing"

    def test_a_permission_403_is_forbidden(self) -> None:
        assert _lookup(_drive_error(403, "insufficientFilePermissions"))("1a").status == "forbidden"

    @pytest.mark.parametrize(
        "reason", ["userRateLimitExceeded", "rateLimitExceeded", "dailyLimitExceeded"]
    )
    def test_a_quota_403_is_the_api_declining_to_answer(self, reason: str) -> None:
        with pytest.raises(UnreachableError, match=reason):
            _lookup(_drive_error(403, reason))("1a")

    def test_a_found_file_reports_its_name_and_trashed_flag(self) -> None:
        state = _lookup({"id": "1a", "name": "SOP", "trashed": True})("1a")

        assert state == GoogleFileState(status="found", name="SOP", trashed=True)


def _google(file_id: str) -> OutboundLink:
    return OutboundLink(kind="google_file", source="s", external_id=file_id)


class TestVerifyGoogleFile:
    def test_a_present_file_is_ok(self) -> None:
        verdict = verify_google_file(
            _google("1a"), lookup=lambda _id: GoogleFileState(status="found", name="SOP")
        )

        assert verdict.verdict == "ok"
        assert "SOP" in verdict.detail

    def test_a_trashed_file_is_broken(self) -> None:
        """The motivating case: someone deleted the doc and the app still links it."""
        verdict = verify_google_file(
            _google("1a"),
            lookup=lambda _id: GoogleFileState(status="found", name="SOP", trashed=True),
        )

        assert verdict.verdict == "broken"
        assert "trashed" in verdict.detail

    def test_a_missing_file_is_broken(self) -> None:
        verdict = verify_google_file(
            _google("1a"), lookup=lambda _id: GoogleFileState(status="missing")
        )

        assert verdict.verdict == "broken"

    def test_a_file_the_service_account_cannot_see_is_broken(self) -> None:
        verdict = verify_google_file(
            _google("1a"), lookup=lambda _id: GoogleFileState(status="forbidden")
        )

        assert verdict.verdict == "broken"
        assert "access" in verdict.detail

    def test_a_transport_failure_is_unreachable(self) -> None:
        def lookup(_id: str) -> GoogleFileState:
            raise UnreachableError("dns")

        assert verify_google_file(_google("1a"), lookup=lookup).verdict == "unreachable"


class TestEnumerateCompanyDefaults:
    def test_a_null_field_is_skipped_not_broken(self) -> None:
        defaults = CompanyDefaults(gdrive_sops_folder_id=None, company_url=None)

        links = [
            link
            for link in enumerate_company_defaults(defaults)
            if link.source.endswith("gdrive_sops_folder_id")
        ]

        assert [(link.kind, link.source) for link in links] == [
            ("skipped", "CompanyDefaults.gdrive_sops_folder_id")
        ]

    def test_google_ids_become_drive_lookups(self) -> None:
        defaults = CompanyDefaults(gdrive_sops_folder_id="1Sops")

        links = enumerate_company_defaults(defaults)

        assert (
            OutboundLink(
                kind="google_file",
                source="CompanyDefaults.gdrive_sops_folder_id",
                external_id="1Sops",
            )
            in links
        )

    def test_a_url_and_id_pair_that_disagree_is_broken_before_any_network_call(self) -> None:
        defaults = CompanyDefaults(
            gdrive_quotes_folder_url="https://drive.google.com/drive/folders/1Other",
            gdrive_quotes_folder_id="1Quotes",
        )

        links = enumerate_company_defaults(defaults)

        mismatch = [link for link in links if link.kind == "broken"]
        assert len(mismatch) == 1
        assert "gdrive_quotes_folder" in mismatch[0].source

    def test_a_url_and_id_pair_that_agree_is_one_lookup(self) -> None:
        defaults = CompanyDefaults(
            gdrive_quotes_folder_url="https://drive.google.com/drive/folders/1Quotes",
            gdrive_quotes_folder_id="1Quotes",
        )

        links = [
            link for link in enumerate_company_defaults(defaults) if link.external_id == "1Quotes"
        ]

        assert len(links) == 1
        assert links[0].kind == "google_file"

    def test_xero_ids_become_xero_lookups(self) -> None:
        defaults = CompanyDefaults(
            xero_tenant_id="tenant-1",
            xero_sales_branding_theme_id="2f9b4e6e-1111-4aaa-8bbb-111111111111",
            xero_payroll_calendar_id="2f9b4e6e-2222-4aaa-8bbb-222222222222",
        )

        kinds = {link.source: link.kind for link in enumerate_company_defaults(defaults)}

        assert kinds["CompanyDefaults.xero_tenant_id"] == "xero_tenant"
        assert kinds["CompanyDefaults.xero_sales_branding_theme_id"] == "xero_branding_theme"
        assert kinds["CompanyDefaults.xero_payroll_calendar_id"] == "xero_payroll_calendar"

    def test_company_url_is_a_plain_http_probe(self) -> None:
        defaults = CompanyDefaults(company_url="https://www.morrissheetmetal.co.nz/")

        assert OutboundLink(
            kind="http",
            source="CompanyDefaults.company_url",
            url="https://www.morrissheetmetal.co.nz/",
        ) in enumerate_company_defaults(defaults)


class FakeXero:
    def __init__(self) -> None:
        self.tenants = {"tenant-1"}
        self.themes = {"theme-1"}
        self.calendars = {"cal-1"}
        self.documents = {("xero_invoice", "inv-1")}

    def tenant_ids(self) -> set[str]:
        return self.tenants

    def branding_theme_ids(self) -> set[str]:
        return self.themes

    def payroll_calendar_ids(self) -> set[str]:
        return self.calendars

    def document_exists(self, kind: str, external_id: str) -> bool:
        return (kind, external_id) in self.documents


class TestVerifyXero:
    def test_a_configured_theme_xero_still_offers_is_ok(self) -> None:
        link = OutboundLink(kind="xero_branding_theme", source="s", external_id="theme-1")

        assert verify_xero(link, xero=FakeXero()).verdict == "ok"

    def test_a_theme_deleted_in_xero_is_broken(self) -> None:
        link = OutboundLink(kind="xero_branding_theme", source="s", external_id="gone")

        verdict = verify_xero(link, xero=FakeXero())

        assert verdict.verdict == "broken"
        assert "gone" in verdict.detail

    def test_tenant_and_calendar_ids_are_checked_against_what_xero_lists(self) -> None:
        ok = OutboundLink(kind="xero_tenant", source="s", external_id="tenant-1")
        bad = OutboundLink(kind="xero_payroll_calendar", source="s", external_id="nope")

        assert verify_xero(ok, xero=FakeXero()).verdict == "ok"
        assert verify_xero(bad, xero=FakeXero()).verdict == "broken"

    def test_a_document_absent_in_the_tenant_is_broken(self) -> None:
        present = OutboundLink(kind="xero_invoice", source="s", external_id="inv-1")
        absent = OutboundLink(kind="xero_invoice", source="s", external_id="inv-2")

        assert verify_xero(present, xero=FakeXero()).verdict == "ok"
        assert verify_xero(absent, xero=FakeXero()).verdict == "broken"

    def test_a_transport_failure_is_unreachable(self) -> None:
        class DownXero(FakeXero):
            def branding_theme_ids(self) -> set[str]:
                raise UnreachableError("token refresh failed")

        link = OutboundLink(kind="xero_branding_theme", source="s", external_id="theme-1")

        assert verify_xero(link, xero=DownXero()).verdict == "unreachable"


class TestVerifyAll:
    def test_every_link_gets_exactly_one_verdict_and_broken_lists_only_the_broken(self) -> None:
        links = [
            _http("https://ok/"),
            _http("https://gone/"),
            _google("1a"),
            OutboundLink(kind="xero_branding_theme", source="s", external_id="theme-1"),
            OutboundLink(kind="skipped", source="CompanyDefaults.company_url"),
            OutboundLink(
                kind="broken", source="CompanyDefaults.gdrive_quotes_folder", detail="mismatch"
            ),
        ]

        report = verify_all(
            links,
            workers=4,
            fetch=lambda url: 404 if "gone" in url else 200,
            google_lookup=lambda _id: GoogleFileState(status="found", name="n"),
            xero=FakeXero(),
        )

        assert len(report.verdicts) == len(links)
        assert {v.link.url or v.link.source for v in report.broken} == {
            "https://gone/",
            "CompanyDefaults.gdrive_quotes_folder",
        }
        assert report.reachable

    def test_verdicts_come_back_in_input_order_across_pooled_and_serial_kinds(self) -> None:
        links = [
            OutboundLink(kind="xero_tenant", source="s", external_id="tenant-1"),
            _http("https://ok/"),
            _google("1a"),
            OutboundLink(kind="skipped", source="x"),
            _http("https://ok2/"),
        ]

        report = verify_all(
            links,
            workers=4,
            fetch=lambda _url: 200,
            google_lookup=lambda _id: GoogleFileState(status="found"),
            xero=FakeXero(),
        )

        assert [v.link for v in report.verdicts] == links

    def test_an_unreachable_target_is_listed_even_when_the_run_answered(self) -> None:
        """The gate fails on these: a Drive that could not be asked is not a Drive that said yes."""

        def lookup(_id: str) -> GoogleFileState:
            raise UnreachableError("token refresh failed")

        report = verify_all(
            [_http("https://ok/"), _google("1a")],
            workers=2,
            fetch=lambda _url: 200,
            google_lookup=lookup,
            xero=FakeXero(),
        )

        assert report.reachable
        assert [v.link.external_id for v in report.unreachable] == ["1a"]

    def test_a_run_that_reached_nothing_is_not_believed(self) -> None:
        """The scraper rule: a run has to have read something to be believed."""

        def fetch(_url: str) -> int:
            raise UnreachableError("no network")

        report = verify_all(
            [_http("https://a/"), _http("https://b/")],
            workers=2,
            fetch=fetch,
            google_lookup=lambda _id: GoogleFileState(status="found"),
            xero=FakeXero(),
        )

        assert not report.reachable
        assert report.broken == []
        assert all(
            isinstance(v, LinkVerdict) and v.verdict == "unreachable" for v in report.verdicts
        )


class TestCli:
    def test_an_unknown_kind_is_refused_not_silently_empty(self) -> None:
        with pytest.raises(SystemExit):
            main(["--kind", "nope"])

    def test_zero_workers_is_refused(self) -> None:
        with pytest.raises(SystemExit):
            main(["--workers", "0"])

    def test_a_negative_sample_is_refused(self) -> None:
        """Django refuses a negative slice with a traceback; argparse refuses it with a message."""
        with pytest.raises(SystemExit):
            main(["--sample", "-1"])


@pytest.mark.django_db
class TestUnclassifiedFields:
    def test_every_link_shaped_column_is_accounted_for(self) -> None:
        """The docstring's contract: a new ``twotalk_call_id`` is red until classified."""
        assert unclassified_fields() == []


@pytest.mark.django_db
class TestEnumerateDatabaseLinks:
    def test_every_link_holding_row_is_enumerated(self) -> None:
        from apps.ai.models.notebook_lm_link import NotebookLmLink
        from apps.job.models import QuoteSpreadsheet
        from apps.process.models.procedure import Procedure

        QuoteSpreadsheet.objects.create(
            sheet_id="1Sheet", sheet_url="https://docs.google.com/spreadsheets/d/1Sheet/edit"
        )
        Procedure.objects.create(
            title="Running the Workshop",
            document_type="procedure",
            google_doc_id="1Doc",
            google_doc_url="https://docs.google.com/document/d/1Doc/edit",
        )
        NotebookLmLink.objects.create(
            name="Training", url="https://notebooklm.google.com/notebook/abc"
        )

        links = enumerate_database_links(sample=5)

        by_source = {link.source: link for link in links}
        assert by_source["QuoteSpreadsheet 1Sheet"].kind == "google_file"
        # A row with neither URL nor id is not news; only the singleton reports unset.
        assert not any(link.detail == "not configured" for link in links)
        assert by_source["Procedure Running the Workshop"].external_id == "1Doc"
        assert by_source["NotebookLmLink Training"].kind == "http"
