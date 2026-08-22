#!/usr/bin/env python
"""Verify every outbound link and external id the app can emit, from an authenticated context.

Fable: The company-defaults screen shipped a "Open Xero Invoice Settings" link
that was a 404, and nothing could have caught it: no tier probes the URLs the
app hands to users. This probe enumerates every such target — string literals
in the tree, the ids and URLs held in ``CompanyDefaults``, every quote
spreadsheet, a sample of the per-document Xero deep links, the gdocs manifest
— and verifies each by the strongest means available:

- Google Drive files and folders through the Drive API as the delegated
  Workspace user (``scripts.gdocs.gauth``). A **trashed** file is broken: that
  is what "I deleted the doc" looks like to the API, and the app would still
  link it.
- Xero ids (tenant, branding theme, payroll calendar, invoices, quotes,
  purchase orders, pay runs) through the app's own Xero client, so the answer
  is the tenant's, not a guess.
- ``go.xero.com`` / ``payroll.xero.com`` pages by an anonymous route probe. Our
  OAuth token authenticates ``api.xero.com``, not the web app, and that is all
  there is — but it is enough: Xero routes before it authenticates, so a real
  page answers ``302`` to the login and an unknown path answers a bare ``404``
  (measured 2026-08-22).
- Everything else by an anonymous HEAD (GET on hosts that refuse HEAD),
  accepting any 2xx/3xx.

Rejected alternatives. An off-the-shelf link checker (lychee and kin) sees
what an anonymous GET sees, and few of these targets are public. A Django
system check runs inside ``scripts/rollback.sh`` and the cutover script, and a
deploy must not depend on vendor credentials or outbound HTTP. A Celery task
would need a result model and a page to read it; nothing surfaces it yet.

This is a script rather than a management command (ADR 0049) because the app
does not read ``GCP_CREDENTIALS`` today — only the gdocs authoring toolchain
does. When the quote-sheet port moves a Drive client into ``apps/``, this
becomes ``manage.py check_links``; ``docs/rewrite-status.md`` carries that
pointer. It is read-only everywhere it reaches, so there is no production
guard on purpose: the instance with the deleted doc is the one to run it on.

It never runs in CI (no credentials; CI stays hermetic). The integration test
in ``scripts/tests/test_outbound_links_integration.py`` is the merge gate.

Usage:
    uv run python -m scripts.ops.outbound_links_probe [--workers 16] [--sample 5]
        [--kind KIND ...] [--json]

Exit 1 when any link is broken; exit 2 when the run reached nothing at all
(a network outage is not ten dead links).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

from scripts import REPO_ROOT
from scripts.bootstrap import setup_django

setup_django()

from apps.core.models import CompanyDefaults  # noqa: E402 -- Django must be configured first

if TYPE_CHECKING:
    from google.oauth2.service_account import Credentials
    from googleapiclient._apis.drive.v3.resources import DriveResource

LinkKind = Literal[
    "http",
    "xero_web",
    "xero_tenant",
    "xero_branding_theme",
    "xero_payroll_calendar",
    "xero_invoice",
    "xero_quote",
    "xero_purchase_order",
    "xero_pay_run",
    "google_file",
    # Decided at enumeration time, before any network call.
    "skipped",
    "broken",
]
Verdict = Literal["ok", "broken", "skipped", "unreachable"]
GoogleIdentity = Literal["delegated", "service-account"]
XeroDocumentKind = Literal["xero_invoice", "xero_quote", "xero_purchase_order", "xero_pay_run"]

XERO_DOCUMENT_KINDS: frozenset[str] = frozenset(
    {"xero_invoice", "xero_quote", "xero_purchase_order", "xero_pay_run"}
)
#: Kinds verified on the thread pool. The Xero kinds stay on the calling thread:
#: the app's client enforces one call per second and a pool would only queue
#: behind it.
POOLED_KINDS: frozenset[str] = frozenset({"http", "xero_web", "google_file"})

#: Where the tree's outbound literals live. ``frontend/src/api/generated`` is
#: derived from ``apps`` (already scanned) and is pruned below.
SOURCE_PATHS: tuple[str, ...] = ("apps", "config", "scripts", "frontend/src", "docs", "CLAUDE.md")
#: ``tests`` is pruned because a URL in a test is a fixture by definition —
#: ``go.xero.com/nope`` and withdrawn product pages are what those files are
#: FOR — while the links users click live in the code under test.
_PRUNED_DIRS: frozenset[str] = frozenset(
    {"node_modules", "__pycache__", "generated", "dist", ".venv", "coverage", "tests"}
)
_TEST_FILE = re.compile(r"(?:\.test\.[jt]sx?|\.spec\.[jt]s|/test_[^/]+\.py)$")

#: Hosts that answer every path alike to an anonymous request and for which
#: the app holds no credential. They are reported as skipped, with the fact,
#: rather than excluded: the report must show what it could not check.
UNVERIFIABLE_HOSTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"^https://[a-z0-9-]+\.atlassian\.net/browse/"),
        (
            "Jira answers 202 and a login redirect to ANY issue key anonymously "
            "(measured 2026-08-22 against KAN-999999); no Jira credential is available to the app"
        ),
    ),
    (
        re.compile(r"^https://[a-z.]+\.googleapis\.com/.*:[A-Za-z]+$"),
        (
            "Google custom method (`:verb`), called by POST; GET answers 404 regardless. "
            "Existence is an integration test's to prove (ADR 0050)"
        ),
    ),
)
_TEXT_SUFFIXES: frozenset[str] = frozenset(
    {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".mjs",
        ".md",
        ".html",
        ".yml",
        ".yaml",
        ".json",
        ".sh",
        ".toml",
        ".txt",
        ".css",
    }
)
MANIFEST = REPO_ROOT / "scripts" / "gdocs" / "google_doc_manifest.json"

#: Braces stay IN the match so a templated URL is recognised and excluded as a
#: template rather than probed as its truncated prefix (which would answer a
#: meaningless 302). Quotes, brackets, backslash and whitespace end a URL.
_URL = re.compile(r"""https?://[^\s'"`<>()\[\]\\]+""")
_TRAILING_PUNCTUATION = ".,;:!?*"

#: Every exclusion carries the fact that makes the host unverifiable. An
#: inconvenient host is not a reason; a host whose existence depends on
#: something other than the code is.
EXCLUDED_URL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"^https?://[^/]*\.test(?::\d+)?(?:/|$)"),
        "RFC 6761 reserved .test TLD: a fixture host",
    ),
    (
        re.compile(r"^https?://[^/]*\.example(?:/|$)"),
        "RFC 2606 reserved .example TLD: a fixture host",
    ),
    (
        re.compile(r"^https?://[^/]*\.invalid(?::\d+)?(?:/|$)"),
        "RFC 2606 reserved .invalid TLD: a host that must never resolve",
    ),
    (
        re.compile(r"^https?://(?:[^/]*\.)?example\.(?:com|org|net)(?::\d+)?(?:/|$)"),
        "RFC 2606 example domain: documentation, not a target",
    ),
    (
        re.compile(r"^https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])"),
        "loopback: exists only where the stack is running",
    ),
    (
        re.compile(r"^https?://[A-Za-z0-9_-]+(?::\d+)?(?:/|$)"),
        "single-label host: a docker service name or a placeholder, never routable",
    ),
    (
        re.compile(r"^https?://[^/]*\$"),
        "shell or nginx variable in the host: a template the script expands at run time",
    ),
    (re.compile(r"^https?://unix:"), "nginx upstream socket, not a URL"),
    (
        re.compile(r"^https://cli\.github\.com/packages$"),
        "apt repository base: apt fetches dists/ beneath it and the base itself answers 404",
    ),
    (
        re.compile(r"\.ngrok-free\.app"),
        "per-developer tunnel: exists only while that developer's ngrok runs",
    ),
    (
        re.compile(r"^https?://[a-z0-9-]+\.docketworks\.site"),
        "per-instance host: which exist depends on which clients are deployed, not on the code",
    ),
    (re.compile(r"[{}]|\$\{"), "template placeholder: not a URL until formatted"),
    (
        re.compile(r"^https?://(?:www\.)?w3\.org/"),
        "XML namespace identifier: an identifier, never fetched",
    ),
)

_GOOGLE_FILE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^https://docs\.google\.com/(?:document|spreadsheets|presentation|forms)/d/([\w-]+)"
    ),
    re.compile(r"^https://drive\.google\.com/drive/(?:u/\d+/)?folders/([\w-]+)"),
    re.compile(r"^https://drive\.google\.com/file/d/([\w-]+)"),
    re.compile(r"^https://drive\.google\.com/open\?id=([\w-]+)"),
)
_XERO_WEB_HOSTS: frozenset[str] = frozenset({"go.xero.com", "payroll.xero.com"})


@dataclass(frozen=True)
class OutboundLink:
    """One thing the app points at, and where it points from."""

    kind: LinkKind
    source: str
    url: str | None = None
    external_id: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class LinkVerdict:
    link: OutboundLink
    verdict: Verdict
    detail: str


@dataclass(frozen=True)
class LinkReport:
    verdicts: tuple[LinkVerdict, ...]

    @property
    def broken(self) -> list[LinkVerdict]:
        return [v for v in self.verdicts if v.verdict == "broken"]

    @property
    def unreachable(self) -> list[LinkVerdict]:
        return [v for v in self.verdicts if v.verdict == "unreachable"]

    @property
    def reachable(self) -> bool:
        """Whether any target answered at all.

        The scraper rule (``apps/quoting/scrapers/base.py``): a run has to have
        read something to be believed. A run of nothing but ``unreachable`` is a
        network problem, not a finding.
        """
        return any(v.verdict in ("ok", "broken") for v in self.verdicts)


class UnreachableError(Exception):
    """The target could not be asked (transport, timeout, auth plumbing) rather than answering."""


class NoSuchHostError(Exception):
    """The host name does not resolve: the link is dead, not the network."""


# --- Enumeration -------------------------------------------------------------


def excluded_reason(url: str) -> str | None:
    """Why this URL is not a probe target, or None when it is one."""
    for pattern, reason in EXCLUDED_URL_PATTERNS:
        if pattern.search(url):
            return reason
    return None


def _unverifiable_reason(url: str) -> str | None:
    for pattern, reason in UNVERIFIABLE_HOSTS:
        if pattern.search(url):
            return reason
    return None


def google_file_id(url: str) -> str | None:
    for pattern in _GOOGLE_FILE_PATTERNS:
        match = pattern.match(url)
        if match:
            return match.group(1)
    return None


def classify_url(url: str, *, source: str) -> OutboundLink:
    """Decide how a URL is verified: Drive id, Xero route probe, plain HTTP — or not at all.

    A placeholder or unverifiable URL classifies as ``skipped`` with the fact,
    so a reserved name held as DATA (the seed fixture's
    ``www.democompany.example.com``) is reported rather than called dead.
    """
    reason = excluded_reason(url) or _unverifiable_reason(url)
    if reason is not None:
        return OutboundLink(kind="skipped", source=source, url=url, detail=reason)
    file_id = google_file_id(url)
    if file_id is not None:
        return OutboundLink(kind="google_file", source=source, url=url, external_id=file_id)
    host = url.split("/", 3)[2].lower()
    if host in _XERO_WEB_HOSTS:
        return OutboundLink(kind="xero_web", source=source, url=url)
    return OutboundLink(kind="http", source=source, url=url)


def _text_files(root: Path, paths: Iterable[str]) -> Iterable[Path]:
    for relative in paths:
        start = root / relative
        if not start.exists():
            raise FileNotFoundError(f"scan path does not exist: {start}")
        if start.is_file():
            yield start
            continue
        for candidate in sorted(start.rglob("*")):
            if any(part in _PRUNED_DIRS for part in candidate.relative_to(root).parts):
                continue
            if not candidate.is_file() or candidate.suffix not in _TEXT_SUFFIXES:
                continue
            if _TEST_FILE.search(candidate.as_posix()):
                continue
            yield candidate


def scan_source_literals(root: Path, *, paths: Sequence[str] = SOURCE_PATHS) -> list[OutboundLink]:
    """Every distinct outbound URL literal under ``paths``, attributed to its first occurrence."""
    seen: dict[str, OutboundLink] = {}
    for file in _text_files(root, paths):
        relative = file.relative_to(root).as_posix()
        for line_number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), start=1):
            for match in _URL.finditer(line):
                url = match.group(0).rstrip(_TRAILING_PUNCTUATION)
                if url in seen or excluded_reason(url) is not None:
                    continue
                source = f"{relative}:{line_number}"
                unverifiable = _unverifiable_reason(url)
                if unverifiable is not None:
                    seen[url] = OutboundLink(
                        kind="skipped", source=source, url=url, detail=unverifiable
                    )
                    continue
                seen[url] = classify_url(url, source=source)
    return list(seen.values())


def _google_pair(url: str | None, file_id: str | None, *, source: str) -> OutboundLink:
    """A URL column and its id column describe one file; they must agree.

    Fable: The pair is redundant by design (the URL is what staff click, the
    id is what the API takes), which makes disagreement a defect in its own
    right — one that no network call can find, so it is decided here.
    """
    if url is None and file_id is None:
        return OutboundLink(kind="skipped", source=source, detail="not configured")
    if url is None:
        return OutboundLink(kind="google_file", source=source, external_id=file_id)
    link = classify_url(url, source=source)
    if file_id is None:
        return link
    if link.kind != "google_file":
        return OutboundLink(
            kind="broken",
            source=source,
            url=url,
            external_id=file_id,
            detail=f"an id is configured but the URL is not a Google Drive link: {url}",
        )
    if link.external_id != file_id:
        return OutboundLink(
            kind="broken",
            source=source,
            url=url,
            external_id=file_id,
            detail=f"URL names file {link.external_id} but the id column holds {file_id}",
        )
    return link


def _configured(value: object, *, kind: LinkKind, source: str) -> OutboundLink:
    if value is None:
        return OutboundLink(kind="skipped", source=source, detail="not configured")
    return OutboundLink(kind=kind, source=source, external_id=str(value))


def enumerate_company_defaults(defaults: CompanyDefaults) -> list[OutboundLink]:
    """Every link or external id the singleton holds."""
    prefix = "CompanyDefaults."
    links: list[OutboundLink] = []
    if defaults.company_url is None:
        links.append(
            OutboundLink(kind="skipped", source=f"{prefix}company_url", detail="not configured")
        )
    else:
        links.append(classify_url(defaults.company_url, source=f"{prefix}company_url"))
    links.append(
        _google_pair(
            defaults.master_quote_template_url,
            defaults.master_quote_template_id,
            source=f"{prefix}master_quote_template_url/_id",
        )
    )
    links.append(
        _google_pair(
            defaults.gdrive_quotes_folder_url,
            defaults.gdrive_quotes_folder_id,
            source=f"{prefix}gdrive_quotes_folder_url/_id",
        )
    )
    for field in (
        "google_shared_drive_id",
        "gdrive_how_we_work_folder_id",
        "gdrive_sops_folder_id",
        "gdrive_reference_library_folder_id",
    ):
        links.append(
            _configured(getattr(defaults, field), kind="google_file", source=f"{prefix}{field}")
        )
    links.append(
        _configured(defaults.xero_tenant_id, kind="xero_tenant", source=f"{prefix}xero_tenant_id")
    )
    links.append(
        _configured(
            defaults.xero_sales_branding_theme_id,
            kind="xero_branding_theme",
            source=f"{prefix}xero_sales_branding_theme_id",
        )
    )
    links.append(
        _configured(
            defaults.xero_payroll_calendar_id,
            kind="xero_payroll_calendar",
            source=f"{prefix}xero_payroll_calendar_id",
        )
    )
    return links


def enumerate_database_links(*, sample: int) -> list[OutboundLink]:
    """Per-record links: every quote spreadsheet, and the latest ``sample`` Xero documents per type.

    The per-document deep links are built from one template each, so the
    template is what can rot and a recent sample proves it; ``sample=0`` checks
    every row for an instance small enough to afford the per-call pacing.
    """
    from apps.accounting.models import Invoice, Quote
    from apps.job.models import QuoteSpreadsheet
    from apps.purchasing.models import PurchaseOrder
    from apps.timesheet.services.payroll_service import build_xero_payroll_url
    from apps.xero.models.xero_payroll import XeroPayRun

    links: list[OutboundLink] = []
    for sheet in QuoteSpreadsheet.objects.select_related("job").order_by("id"):
        label = (
            f"QuoteSpreadsheet job {sheet.job.job_number}"
            if sheet.job
            else f"QuoteSpreadsheet {sheet.id}"
        )
        links.append(_google_pair(sheet.sheet_url, sheet.sheet_id, source=label))

    def latest[T](queryset: Iterable[T]) -> list[T]:
        rows = list(queryset)
        return rows if sample == 0 else rows[:sample]

    for invoice in latest(Invoice.objects.exclude(online_url=None).order_by("-date", "-number")):
        source = f"Invoice {invoice.number}"
        links.append(classify_url(invoice.online_url or "", source=source))
        links.append(
            OutboundLink(kind="xero_invoice", source=source, external_id=str(invoice.xero_id))
        )
    for quote in latest(Quote.objects.exclude(online_url=None).order_by("-date", "-number")):
        source = f"Quote {quote.number}"
        links.append(classify_url(quote.online_url or "", source=source))
        links.append(OutboundLink(kind="xero_quote", source=source, external_id=str(quote.xero_id)))
    for order in latest(
        PurchaseOrder.objects.exclude(online_url=None)
        .exclude(xero_id=None)
        .order_by("-order_date", "-po_number")
    ):
        source = f"PurchaseOrder {order.po_number}"
        links.append(classify_url(order.online_url or "", source=source))
        links.append(
            OutboundLink(kind="xero_purchase_order", source=source, external_id=str(order.xero_id))
        )
    for pay_run in latest(XeroPayRun.objects.order_by("-payment_date")):
        source = f"XeroPayRun {pay_run.payment_date}"
        if CompanyDefaults.get_solo().xero_shortcode is None:
            links.append(
                OutboundLink(kind="skipped", source=source, detail="xero_shortcode not configured")
            )
        else:
            links.append(classify_url(build_xero_payroll_url(pay_run.xero_id), source=source))
        links.append(
            OutboundLink(kind="xero_pay_run", source=source, external_id=str(pay_run.xero_id))
        )
    return links


_MANIFEST_NEEDS_DELEGATION = (
    "authored by the gdocs toolchain as the delegated Workspace user; the service account "
    "cannot see them (Drive answers 404 for unshared files), so run with --google-as delegated"
)


def enumerate_manifest(path: Path, *, google_as: GoogleIdentity) -> list[OutboundLink]:
    """Every document and folder id the gdocs authoring manifest records.

    These are verifiable only as the identity that wrote them, so under the
    service account they are reported as skipped with that fact rather than
    as three files Drive "has no" record of.
    """
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise TypeError(f"{path} must be a JSON object keyed by document id")
    links: list[OutboundLink] = []
    folders: dict[str, str] = {}
    for doc_id, entry in manifest.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("title"), str):
            raise TypeError(f"{path}: entry {doc_id} has no title")
        title = entry["title"]
        links.append(
            OutboundLink(kind="google_file", source=f"{path.name}: {title}", external_id=doc_id)
        )
        folder = entry.get("folder_id")
        if isinstance(folder, str):
            folders.setdefault(folder, f"{path.name}: folder of {title}")
    links.extend(
        OutboundLink(kind="google_file", source=source, external_id=folder)
        for folder, source in folders.items()
    )
    if google_as == "delegated":
        return links
    return [
        OutboundLink(
            kind="skipped",
            source=link.source,
            external_id=link.external_id,
            detail=_MANIFEST_NEEDS_DELEGATION,
        )
        for link in links
    ]


def enumerate_links(
    *, sample: int, google_as: GoogleIdentity, root: Path = REPO_ROOT
) -> list[OutboundLink]:
    """Everything the probe checks, in a stable order."""
    return [
        *scan_source_literals(root),
        *enumerate_company_defaults(CompanyDefaults.get_solo()),
        *enumerate_database_links(sample=sample),
        *enumerate_manifest(
            root / "scripts" / "gdocs" / "google_doc_manifest.json", google_as=google_as
        ),
    ]


# --- Verification ------------------------------------------------------------

_ROUTED_STATUSES: frozenset[int] = frozenset({400, 401, 403, 405})

HttpFetch = Callable[[str], int]
"""Final HTTP status after redirects; raises ``UnreachableError`` when the host cannot be asked."""


@dataclass(frozen=True)
class GoogleFileState:
    status: Literal["found", "missing", "forbidden"]
    name: str = ""
    trashed: bool = False


GoogleLookup = Callable[[str], GoogleFileState]


class XeroLookups(Protocol):
    def tenant_ids(self) -> set[str]: ...
    def branding_theme_ids(self) -> set[str]: ...
    def payroll_calendar_ids(self) -> set[str]: ...
    def document_exists(self, kind: str, external_id: str) -> bool: ...


def verify_http(link: OutboundLink, *, fetch: HttpFetch) -> LinkVerdict:
    if link.url is None:
        raise ValueError(f"{link.source}: an http link needs a URL")
    try:
        status = fetch(link.url)
    except UnreachableError as exc:
        return LinkVerdict(link, "unreachable", str(exc))
    except NoSuchHostError as exc:
        return LinkVerdict(link, "broken", f"host does not resolve: {exc}")
    note = " (route probe; the web app cannot be authenticated)" if link.kind == "xero_web" else ""
    if 200 <= status < 400:
        return LinkVerdict(link, "ok", f"HTTP {status}{note}")
    if status in _ROUTED_STATUSES:
        # The server identified the resource well enough to demand credentials
        # or another method — api.xero.com answers 401, a POST-only token
        # endpoint answers 400 — which is existence, the only thing an
        # anonymous probe can establish.
        return LinkVerdict(
            link, "ok", f"HTTP {status}: exists, needs credentials or another method"
        )
    return LinkVerdict(link, "broken", f"HTTP {status}{note}")


def verify_google_file(link: OutboundLink, *, lookup: GoogleLookup) -> LinkVerdict:
    if link.external_id is None:
        raise ValueError(f"{link.source}: a google_file link needs a file id")
    try:
        state = lookup(link.external_id)
    except UnreachableError as exc:
        return LinkVerdict(link, "unreachable", str(exc))
    if state.status == "missing":
        return LinkVerdict(
            link,
            "broken",
            f"Drive has no file {link.external_id} visible to this identity "
            "(it answers 404 for unshared files too)",
        )
    if state.status == "forbidden":
        return LinkVerdict(
            link, "broken", f"no access to file {link.external_id} as the delegated user"
        )
    if state.trashed:
        return LinkVerdict(link, "broken", f"{state.name!r} is trashed")
    return LinkVerdict(link, "ok", state.name)


def verify_xero(link: OutboundLink, *, xero: XeroLookups) -> LinkVerdict:
    if link.external_id is None:
        raise ValueError(f"{link.source}: a Xero link needs an external id")
    try:
        if link.kind == "xero_tenant":
            present = link.external_id in xero.tenant_ids()
        elif link.kind == "xero_branding_theme":
            present = link.external_id in xero.branding_theme_ids()
        elif link.kind == "xero_payroll_calendar":
            present = link.external_id in xero.payroll_calendar_ids()
        elif link.kind in XERO_DOCUMENT_KINDS:
            present = xero.document_exists(link.kind, link.external_id)
        else:
            raise ValueError(f"{link.source}: {link.kind} is not a Xero kind")
    except UnreachableError as exc:
        return LinkVerdict(link, "unreachable", str(exc))
    if present:
        return LinkVerdict(link, "ok", "Xero lists it")
    return LinkVerdict(
        link, "broken", f"Xero has no {link.kind.removeprefix('xero_')} {link.external_id}"
    )


def verify_all(
    links: Sequence[OutboundLink],
    *,
    workers: int,
    fetch: HttpFetch,
    google_lookup: GoogleLookup,
    xero: XeroLookups,
) -> LinkReport:
    """One verdict per link, in input order; pooled kinds concurrently, Xero kinds serially."""

    def pooled(link: OutboundLink) -> LinkVerdict:
        if link.kind == "google_file":
            return verify_google_file(link, lookup=google_lookup)
        return verify_http(link, fetch=fetch)

    results: dict[int, LinkVerdict] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            index: pool.submit(pooled, link)
            for index, link in enumerate(links)
            if link.kind in POOLED_KINDS
        }
        for index, link in enumerate(links):
            if link.kind == "skipped":
                results[index] = LinkVerdict(link, "skipped", link.detail)
            elif link.kind == "broken":
                results[index] = LinkVerdict(link, "broken", link.detail)
            elif link.kind not in POOLED_KINDS:
                results[index] = verify_xero(link, xero=xero)
        for index, future in futures.items():
            results[index] = future.result()
    return LinkReport(tuple(results[index] for index in range(len(links))))


# --- Live adapters -------------------------------------------------------------

_REQUEST_TIMEOUT = (10, 30)
_USER_AGENT = "docketworks-outbound-links-probe"


def requests_fetch(url: str) -> int:
    """Final status after redirects, by a streamed GET whose body is never read.

    Not HEAD: go.xero.com and payroll.xero.com answer 503 to every HEAD and
    portal.steelandtube.co.nz answers 404 to it, while GET discriminates on
    all three (measured 2026-08-22). A 5xx or a transport error is retried
    once so a single blip does not read as a finding.
    """
    import requests

    headers = {"User-Agent": _USER_AGENT}
    last: UnreachableError | None = None
    for _attempt in range(2):
        try:
            answer = requests.get(
                url, allow_redirects=True, timeout=_REQUEST_TIMEOUT, headers=headers, stream=True
            )
            answer.close()
        except requests.ConnectionError as exc:
            if _is_name_resolution_failure(exc):
                raise NoSuchHostError(url.split("/", 3)[2]) from exc
            last = UnreachableError(f"{type(exc).__name__}: {exc}")
            continue
        except requests.RequestException as exc:
            last = UnreachableError(f"{type(exc).__name__}: {exc}")
            continue
        if answer.status_code < 500:
            return answer.status_code
        last = None
        final = answer.status_code
    if last is not None:
        raise last
    return final


def _is_name_resolution_failure(exc: Exception) -> bool:
    # urllib3 wraps getaddrinfo's failure as NameResolutionError; requests
    # wraps that again, so the class is only reachable through the message.
    return "NameResolutionError" in str(exc)


def google_credentials(identity: GoogleIdentity) -> Credentials:
    """Who asks Drive. Both answers are meaningful, so the operator chooses.

    ``delegated`` impersonates the Workspace user the app acts as
    (``GCP_DELEGATED_SUBJECT`` or ``CompanyDefaults.company_email``) and sees
    what staff see — the right view on a client instance. ``service-account``
    sees what is shared with the key itself, which is the only view on a dev
    box whose ``company_email`` is the seed placeholder. Neither falls back
    to the other: a probe that quietly switched identities would report a
    file as missing that the other identity can see.
    """
    from scripts.gdocs.gauth import DRIVE_SCOPE, delegated_credentials, service_account_credentials

    if identity == "delegated":
        return delegated_credentials([DRIVE_SCOPE])
    return service_account_credentials([DRIVE_SCOPE])


class DriveLookup:
    """``files.get`` with the given credentials, one Drive client per thread.

    googleapiclient discovery objects are not thread-safe (each owns an
    ``httplib2.Http``), so the credentials are built once and a client per
    worker thread is built from them on first use.
    """

    def __init__(self, *, credentials: Callable[[], Credentials]) -> None:
        self._local = threading.local()
        self._credentials_lock = threading.Lock()
        self._build_credentials = credentials
        self._credentials: Credentials | None = None

    def _drive(self) -> DriveResource:
        from googleapiclient.discovery import build

        drive: DriveResource | None = getattr(self._local, "drive", None)
        if drive is not None:
            return drive
        with self._credentials_lock:
            if self._credentials is None:
                self._credentials = self._build_credentials()
        drive = build("drive", "v3", credentials=self._credentials, cache_discovery=False)
        self._local.drive = drive
        return drive

    def __call__(self, file_id: str) -> GoogleFileState:
        from googleapiclient.errors import HttpError

        try:
            found = (
                self._drive()
                .files()
                .get(fileId=file_id, supportsAllDrives=True, fields="id,name,trashed")
                .execute()
            )
        except HttpError as exc:
            if exc.status_code == 404:
                return GoogleFileState(status="missing")
            if exc.status_code == 403:
                return GoogleFileState(status="forbidden")
            raise UnreachableError(
                f"Drive answered {exc.status_code} for {file_id}: {exc.reason}"
            ) from exc
        except OSError as exc:
            raise UnreachableError(f"{type(exc).__name__}: {exc}") from exc
        return GoogleFileState(
            status="found",
            name=str(found.get("name", "")),
            trashed=bool(found.get("trashed", False)),
        )


class LiveXero:
    """The app's own Xero client, each listing fetched once per run."""

    def __init__(self) -> None:
        self._tenants: set[str] | None = None
        self._themes: set[str] | None = None
        self._calendars: set[str] | None = None

    def tenant_ids(self) -> set[str]:
        if self._tenants is None:
            from xero_python.identity import IdentityApi

            from apps.xero.auth import get_api_client

            connections = self._ask(lambda: IdentityApi(get_api_client()).get_connections())
            self._tenants = {str(connection.tenant_id) for connection in connections}
        return self._tenants

    def branding_theme_ids(self) -> set[str]:
        if self._themes is None:
            from apps.xero.provider import XeroAccountingProvider

            themes = self._ask(XeroAccountingProvider().list_document_themes)
            self._themes = {theme.external_id for theme in themes}
        return self._themes

    def payroll_calendar_ids(self) -> set[str]:
        if self._calendars is None:
            from apps.xero.auth import get_tenant_id
            from apps.xero.payroll_setup import get_payroll_calendars

            calendars = self._ask(lambda: get_payroll_calendars(tenant_id=get_tenant_id()))
            self._calendars = {calendar.id for calendar in calendars}
        return self._calendars

    def document_exists(self, kind: str, external_id: str) -> bool:
        from xero_python.accounting import AccountingApi
        from xero_python.exceptions import ApiException
        from xero_python.payrollnz import PayrollNzApi

        from apps.xero.auth import get_api_client, get_tenant_id

        tenant_id = get_tenant_id()
        accounting = AccountingApi(get_api_client())
        try:
            if kind == "xero_invoice":
                rows = accounting.get_invoice(tenant_id, external_id).invoices
            elif kind == "xero_quote":
                rows = accounting.get_quote(tenant_id, external_id).quotes
            elif kind == "xero_purchase_order":
                rows = accounting.get_purchase_order(tenant_id, external_id).purchase_orders
            elif kind == "xero_pay_run":
                rows = [PayrollNzApi(get_api_client()).get_pay_run(tenant_id, external_id).pay_run]
            else:
                raise ValueError(f"{kind} is not a Xero document kind")
        except ApiException as exc:
            # deliberate-swallow: a 404 is the answer this function exists to
            # give; anything else is the vendor not answering.
            if exc.status == 404:
                return False
            raise UnreachableError(
                f"Xero answered {exc.status} for {kind} {external_id}: {exc.reason}"
            ) from exc
        return bool(rows)

    @staticmethod
    def _ask[T](call: Callable[[], T]) -> T:
        from xero_python.exceptions import ApiException

        try:
            return call()
        except (ApiException, RuntimeError, OSError) as exc:
            # deliberate-swallow: converted to the probe's typed "could not ask"
            # outcome; RuntimeError is how apps.xero.auth reports a missing or
            # unrefreshable token.
            raise UnreachableError(f"{type(exc).__name__}: {exc}") from exc


# --- CLI -------------------------------------------------------------------------

_VERDICT_ORDER: dict[str, int] = {"broken": 0, "unreachable": 1, "ok": 2, "skipped": 3}


def render(report: LinkReport) -> str:
    lines = []
    for verdict in sorted(
        report.verdicts, key=lambda v: (_VERDICT_ORDER[v.verdict], v.link.source)
    ):
        target = verdict.link.url or verdict.link.external_id or ""
        lines.append(
            f"{verdict.verdict:<11} {verdict.link.kind:<22} {verdict.link.source}  "
            f"{target}  {verdict.detail}"
        )
    counts = ", ".join(
        f"{name} {len([v for v in report.verdicts if v.verdict == name])}"
        for name in _VERDICT_ORDER
    )
    lines.append(f"\n{len(report.verdicts)} targets: {counts}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--workers", type=int, default=16, help="threads for HTTP and Drive lookups"
    )
    parser.add_argument(
        "--sample", type=int, default=5, help="latest N Xero documents per type; 0 = all"
    )
    parser.add_argument("--kind", action="append", help="only these link kinds (repeatable)")
    parser.add_argument(
        "--google-as",
        choices=("delegated", "service-account"),
        default="delegated",
        help="which identity asks Drive (see google_credentials)",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable verdicts")
    args = parser.parse_args(argv)

    links = enumerate_links(sample=args.sample, google_as=args.google_as)
    if args.kind:
        links = [link for link in links if link.kind in args.kind]
    report = verify_all(
        links,
        workers=args.workers,
        fetch=requests_fetch,
        google_lookup=DriveLookup(credentials=lambda: google_credentials(args.google_as)),
        xero=LiveXero(),
    )

    if args.json:
        print(
            json.dumps(
                [
                    {**asdict(v.link), "verdict": v.verdict, "verdict_detail": v.detail}
                    for v in report.verdicts
                ],
                indent=2,
            )
        )
    else:
        print(render(report))
    if not report.reachable:
        print(
            "Nothing answered: this is a network or credential problem, not a link finding.",
            file=sys.stderr,
        )
        return 2
    return 1 if report.broken else 0


if __name__ == "__main__":
    sys.exit(main())
