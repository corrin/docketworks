#!/usr/bin/env python
"""Verify every outbound link and external id the app can emit, from an authenticated context.

Fable: The company-defaults screen shipped a "Open Xero Invoice Settings" link
that was a 404, and nothing could have caught it: no tier probes the URLs the
app hands to users. This probe enumerates every such target and verifies each
by the strongest means available:

- Google Drive files and folders through the Drive API, as an identity the
  operator names (``--google-as``). A **trashed** file is broken: that is what
  "I deleted the doc" looks like to the API, and the app would still link it.
- Xero ids (tenant, branding theme, payroll calendar, invoices, quotes,
  purchase orders, pay runs) through the app's own Xero client, so the answer
  is the tenant's, not a guess.
- ``go.xero.com`` / ``payroll.xero.com`` pages by an anonymous GET route
  probe. Our OAuth token authenticates ``api.xero.com``, not the web app, and
  that is all there is — but it is enough for a static page: Xero routes
  before it authenticates, so a real page answers ``302`` to the login and an
  unknown path a bare ``404`` (measured 2026-08-22). For a per-document deep
  link the route probe answers 200 for ANY id, so the paired Xero-id check is
  the truth and the route probe only proves the template.
- Everything else by an anonymous GET with the body unread, accepting any
  2xx/3xx, and accepting 400/401/403/405 as "exists, needs credentials or
  another method". A soft 404 (a dead page that redirects to a 200 home page)
  reads as ok; that is inherent to any anonymous probe.

Where the targets come from — and why a new integration cannot be missed:

- Every ``http(s)://`` literal in the tree (``SOURCE_PATHS``), minus fixture
  hosts and templates (``EXCLUDED_URL_PATTERNS``, each with its reason).
  Nothing to register.
- Every ``URLField`` on every first-party model, discovered from Django's
  model registry. Nothing to register either: a ``twotalk_url = URLField()``
  is probed the day it exists.
- Every non-relation ``*_id`` column on every first-party model, which a type
  cannot identify, so it is classified in ``EXTERNAL_ID_FIELDS`` (verified by
  kind), ``UNVERIFIED_EXTERNAL_ID_FIELDS`` (a vendor id with no verifier yet,
  reported as skipped) or ``NOT_A_LINK_FIELDS`` (our own ids). An unclassified
  column fails ``unclassified_fields()`` — which the hermetic unit suite, and
  therefore CI, asserts empty — so forgetting one is a red commit, not a gap.

Rejected alternatives. An off-the-shelf link checker (lychee and kin) sees
what an anonymous GET sees, and few of these targets are public. A Django
system check runs inside ``scripts/rollback.sh`` and the cutover script, and a
deploy must not depend on vendor credentials or outbound HTTP. A Celery task
would need a result model and a page to read it; nothing surfaces it yet.

This is a script rather than a management command (ADR 0049) because the app
does not read ``GCP_CREDENTIALS`` today — only the gdocs authoring toolchain
does. When the quote-sheet port moves a Drive client into ``apps/`` (reading
the service-account JSON from an ``IntegrationSettings`` column, ADR 0053),
this becomes ``manage.py check_links``; ``docs/rewrite-status.md`` carries
that pointer. It is read-only everywhere it reaches, so there is no production
guard on purpose: the instance with the deleted doc is the one to run it on.

It never runs in CI (no credentials; CI stays hermetic). The integration test
in ``scripts/tests/test_outbound_links_integration.py`` is the merge gate.

Usage:
    uv run python -m scripts.ops.outbound_links_probe [--workers 16] [--sample 5]
        [--kind KIND ...] [--google-as delegated|service-account] [--json]

Exit 1 when any link is broken or could not be asked; exit 2 when the run
reached nothing at all (a network outage is not ten dead links).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import threading
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, get_args
from urllib.parse import urlsplit

from scripts import REPO_ROOT
from scripts.bootstrap import setup_django

setup_django()

from django.apps import apps as django_apps  # noqa: E402 -- Django must be configured first
from django.db import models  # noqa: E402

from apps.core.models import CompanyDefaults  # noqa: E402

if TYPE_CHECKING:
    from google.oauth2.service_account import Credentials
    from googleapiclient._apis.drive.v3.resources import DriveResource
    from googleapiclient.errors import HttpError

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
XeroListKind = Literal["xero_tenant", "xero_branding_theme", "xero_payroll_calendar"]

LINK_KINDS: tuple[str, ...] = get_args(LinkKind)
XERO_DOCUMENT_KINDS: frozenset[str] = frozenset(get_args(XeroDocumentKind))
XERO_LIST_KINDS: frozenset[str] = frozenset(get_args(XeroListKind))
#: Kinds verified on the thread pool. The Xero kinds stay on the calling thread:
#: the app's client enforces one call per second and a pool would only queue
#: behind it.
POOLED_KINDS: frozenset[str] = frozenset({"http", "xero_web", "google_file"})

#: Where the tree's outbound literals live. ``frontend/src/api/generated`` is
#: derived from ``apps`` (already scanned) and is pruned below.
SOURCE_PATHS: tuple[str, ...] = ("apps", "config", "scripts", "frontend/src", "docs", "CLAUDE.md")
#: Fable: ``tests`` is pruned because a URL in a test is a fixture by definition
#: — ``go.xero.com/nope`` and withdrawn product pages are what those files are
#: FOR — while the links users click live in the code under test.
_PRUNED_DIRS: frozenset[str] = frozenset(
    {"node_modules", "__pycache__", "generated", "dist", ".venv", "coverage", "tests"}
)
_TEST_FILE = re.compile(r"(?:\.test\.[jt]sx?|\.spec\.[jt]s|/test_[^/]+\.py)$")
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
        ".template",
        ".conf",
    }
)

#: Fable: Braces stay IN the match so a templated URL is recognised and excluded
#: as a template rather than probed as its truncated prefix (which would answer
#: a meaningless 302). Quotes, brackets, backslash and whitespace end a URL, so
#: a Wikipedia-style ``Foo_(bar)`` path would be cut at the paren — none in
#: the tree today.
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
        # Fable: ``www.`` is the marketing site and a real target; every other
        # label is an instance name.
        re.compile(r"^https?://(?!www\.)[a-z0-9-]+\.docketworks\.site"),
        "per-instance host: which exist depends on which clients are deployed, not on the code",
    ),
    (
        re.compile(r"[{}]|\$\{|__[A-Z][A-Z0-9_]*__"),
        "template placeholder: not a URL until formatted",
    ),
    (
        re.compile(r"^https?://(?:www\.)?w3\.org/"),
        "XML namespace identifier: an identifier, never fetched",
    ),
)

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

#: Fable: ``/d/e/<token>`` is a publish token, not a file id, so it is left to
#: the anonymous probe (published docs are public by definition).
_GOOGLE_FILE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^https://docs\.google\.com/(?:document|spreadsheets|presentation|forms)/d/(?!e/)([\w-]+)"
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
    """The host name does not exist: the link is dead, not the network."""


# --- Classification ----------------------------------------------------------------


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
    ``www.democompany.example.com``) is reported rather than called dead. A
    value with no http(s) scheme is ``broken`` here, before any network call:
    a v1 row without a scheme is a defect in the data, reported, never a
    traceback.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return OutboundLink(
            kind="broken", source=source, url=url, detail=f"not an http(s) URL: {url!r}"
        )
    reason = excluded_reason(url) or _unverifiable_reason(url)
    if reason is not None:
        return OutboundLink(kind="skipped", source=source, url=url, detail=reason)
    file_id = google_file_id(url)
    if file_id is not None:
        return OutboundLink(kind="google_file", source=source, url=url, external_id=file_id)
    if parts.hostname in _XERO_WEB_HOSTS:
        return OutboundLink(kind="xero_web", source=source, url=url)
    return OutboundLink(kind="http", source=source, url=url)


# --- Enumeration: the tree ---------------------------------------------------------


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
    """Every distinct outbound URL literal under ``paths``, attributed to its first occurrence.

    Fable: Excluded literals are dropped here rather than reported: the tree
    holds dozens of fixture hosts and f-string templates, and the report is
    for what could not be verified, not for what was never a target. The
    Xero deep-link templates dropped this way are covered by the per-document
    rows ``enumerate_database_links`` samples.
    """
    seen: dict[str, OutboundLink] = {}
    for file in _text_files(root, paths):
        relative = file.relative_to(root).as_posix()
        for line_number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), start=1):
            for match in _URL.finditer(line):
                url = match.group(0).rstrip(_TRAILING_PUNCTUATION)
                if url in seen or excluded_reason(url) is not None:
                    continue
                seen[url] = classify_url(url, source=f"{relative}:{line_number}")
    return list(seen.values())


# --- Enumeration: the database ------------------------------------------------------

#: Fable: ``*_id`` columns that are vendor ids the probe can verify, by kind.
#: Keyed ``app_label.Model.field``. A column here is checked on every row
#: (Google, cheap and pooled) or on the latest ``--sample`` rows (Xero
#: documents, one call per second).
EXTERNAL_ID_FIELDS: dict[str, LinkKind] = {
    "core.CompanyDefaults.xero_tenant_id": "xero_tenant",
    "core.CompanyDefaults.xero_sales_branding_theme_id": "xero_branding_theme",
    "core.CompanyDefaults.xero_payroll_calendar_id": "xero_payroll_calendar",
    "core.CompanyDefaults.master_quote_template_id": "google_file",
    "core.CompanyDefaults.gdrive_quotes_folder_id": "google_file",
    "core.CompanyDefaults.google_shared_drive_id": "google_file",
    "core.CompanyDefaults.gdrive_how_we_work_folder_id": "google_file",
    "core.CompanyDefaults.gdrive_sops_folder_id": "google_file",
    "core.CompanyDefaults.gdrive_reference_library_folder_id": "google_file",
    "job.QuoteSpreadsheet.sheet_id": "google_file",
    "process.Procedure.google_doc_id": "google_file",
    "accounting.Invoice.xero_id": "xero_invoice",
    "accounting.Quote.xero_id": "xero_quote",
    "purchasing.PurchaseOrder.xero_id": "xero_purchase_order",
    "xero.XeroPayRun.xero_id": "xero_pay_run",
    "xero.XeroPayRun.payroll_calendar_id": "xero_payroll_calendar",
}

_TENANT_PER_ROW = "Xero tenant per row: the singleton's tenant is checked"

#: Vendor ids with no verifier yet: each is reported once, as skipped, so the
#: report shows what it did not check. Adding a verifier moves the entry up.
UNVERIFIED_EXTERNAL_ID_FIELDS: dict[str, str] = {
    "accounts.Staff.xero_user_id": "Xero user id: no verifier yet",
    "accounts.Staff.xero_tenant_id": _TENANT_PER_ROW,
    "accounts.StaffPayrollTerm.xero_salary_wage_id": "Xero salary/wage id: no verifier yet",
    "accounts.StaffPayrollTerm.xero_working_pattern_id": "Xero working pattern: no verifier yet",
    "company.Company.xero_contact_id": "Xero contact id: no verifier yet",
    "company.Company.xero_tenant_id": _TENANT_PER_ROW,
    "company.Company.xero_merged_into_id": "Xero contact id (merge target): no verifier yet",
    "company.Supplier.xero_contact_id": "Xero contact id: no verifier yet",
    "company.Supplier.xero_tenant_id": _TENANT_PER_ROW,
    "company.Supplier.xero_merged_into_id": "Xero contact id (merge target): no verifier yet",
    "company.SupplierPickupAddress.google_place_id": "Google Places id: no verifier yet",
    "crm.PhoneCallRecord.provider_call_id": "phone provider call id: no verifier yet",
    "crm.PhoneCallRecording.provider_recording_id": "phone provider recording: no verifier yet",
    "job.CostLine.xero_time_id": "Xero Projects time id: no verifier yet",
    "job.CostLine.xero_expense_id": "Xero Projects expense id: no verifier yet",
    "job.Job.xero_project_id": "Xero Projects project id: no verifier yet",
    "job.Job.xero_default_task_id": "Xero Projects task id: no verifier yet",
    "purchasing.PurchaseOrder.xero_tenant_id": _TENANT_PER_ROW,
    "purchasing.PurchaseOrderLine.xero_line_item_id": "Xero line item id: no verifier yet",
    "purchasing.Stock.xero_id": "Xero item id: no verifier yet",
    "quoting.SupplierProduct.variant_id": "supplier variant id: the scraper owns product liveness",
    "accounting.Invoice.xero_tenant_id": _TENANT_PER_ROW,
    "accounting.Bill.xero_id": "Xero bill id: no verifier yet",
    "accounting.Bill.xero_tenant_id": _TENANT_PER_ROW,
    "accounting.CreditNote.xero_id": "Xero credit note id: no verifier yet",
    "accounting.CreditNote.xero_tenant_id": _TENANT_PER_ROW,
    "accounting.InvoiceLineItem.xero_line_id": "Xero line item id: no verifier yet",
    "accounting.BillLineItem.xero_line_id": "Xero line item id: no verifier yet",
    "accounting.CreditNoteLineItem.xero_line_id": "Xero line item id: no verifier yet",
    "accounting.Quote.xero_tenant_id": _TENANT_PER_ROW,
    "xero.XeroAccount.xero_id": "Xero account id: no verifier yet",
    "xero.XeroAccount.xero_tenant_id": _TENANT_PER_ROW,
    "xero.XeroPayItem.xero_id": "Xero pay item id: no verifier yet",
    "xero.XeroPayItem.xero_tenant_id": _TENANT_PER_ROW,
    "xero.XeroPayRun.xero_tenant_id": _TENANT_PER_ROW,
    "xero.XeroPaySlip.xero_id": "Xero pay slip id: no verifier yet",
    "xero.XeroPaySlip.xero_tenant_id": _TENANT_PER_ROW,
    "xero.XeroPaySlip.xero_employee_id": "Xero employee id: no verifier yet",
}

#: ``*_id`` columns that name nothing outside this database.
NOT_A_LINK_FIELDS: dict[str, str] = {
    "core.AppError.job_id": "our own row id, held loosely so the error outlives the job",
    "core.AppError.user_id": "our own row id",
    "job.JobEvent.change_id": "delta-checksum change id",
    "job.JobDeltaRejection.change_id": "delta-checksum change id",
    "job.JobQuoteChat.message_id": "chat message id, ours",
    "timesheet.LeaveRequest.batch_id": "our batch id",
    "purchasing.Stock.active_source_purchase_order_line_id": "our own row id",
    "xero.XeroApp.client_id": "OAuth client id: a credential, not a link",
    "xero.XeroError.job_id": "our own row id",
    "xero.XeroError.user_id": "our own row id",
    "xero.XeroError.reference_id": (
        "Xero id of the entity that failed, kept on the error row for diagnosis; "
        "never emitted as a link"
    ),
    "search.SearchTelemetryEvent.selected_result_id": "our own row id",
    "diagnostics.SessionReplayRecording.job_id": "our own row id",
    "diagnostics.SessionReplayChunk.job_id": "our own row id",
    "accounts.HistoricalStaff.xero_user_id": "history mirror of Staff",
    "accounts.HistoricalStaff.xero_tenant_id": "history mirror of Staff",
    "process.HistoricalProcedure.google_doc_id": "history mirror of Procedure",
}

#: ``URLField`` columns not probed row by row, with the reason.
SKIPPED_URL_FIELDS: dict[str, str] = {
    "quoting.SupplierProduct.url": (
        "thousands of product pages: the scraper's discontinue sweep owns their liveness (ADR 0039)"
    ),
    "process.HistoricalProcedure.google_doc_url": "history mirror of Procedure",
}

#: A URL column and an id column that describe one Google file; they must agree.
GOOGLE_URL_ID_PAIRS: dict[str, str] = {
    "core.CompanyDefaults.master_quote_template_url": (
        "core.CompanyDefaults.master_quote_template_id"
    ),
    "core.CompanyDefaults.gdrive_quotes_folder_url": "core.CompanyDefaults.gdrive_quotes_folder_id",
    "job.QuoteSpreadsheet.sheet_url": "job.QuoteSpreadsheet.sheet_id",
    "process.Procedure.google_doc_url": "process.Procedure.google_doc_id",
}

#: Fable: Which rows are "latest" when sampling. UUID primary keys carry no
#: order, so the first of these that the model has is used, else the key.
_RECENCY_FIELDS: tuple[str, ...] = (
    "date",
    "payment_date",
    "order_date",
    "created_at",
    "updated_at",
)
_LABEL_FIELDS: tuple[str, ...] = (
    "number",
    "po_number",
    "title",
    "name",
    "sheet_id",
    "payment_date",
)


def _field_label(model: type[models.Model], field: models.Field[object, object]) -> str:
    return f"{model._meta.app_label}.{model.__name__}.{field.name}"


def _first_party_models() -> list[type[models.Model]]:
    return [
        model
        for app_config in django_apps.get_app_configs()
        if app_config.name.startswith("apps.")
        for model in app_config.get_models()
    ]


def _link_fields(model: type[models.Model]) -> list[models.Field[object, object]]:
    """Every column that could name something outside this database."""
    return [
        field
        for field in model._meta.concrete_fields
        if not field.is_relation
        and not field.primary_key
        and (isinstance(field, models.URLField) or field.name.endswith("_id"))
    ]


def unclassified_fields() -> list[str]:
    """Link-shaped columns the registries above do not account for.

    Asserted empty by the hermetic unit suite, so a new ``twotalk_call_id``
    turns a commit red until it is classified.
    """
    known = (
        EXTERNAL_ID_FIELDS.keys()
        | UNVERIFIED_EXTERNAL_ID_FIELDS.keys()
        | NOT_A_LINK_FIELDS.keys()
        | SKIPPED_URL_FIELDS.keys()
        | GOOGLE_URL_ID_PAIRS.keys()
    )
    missing: list[str] = []
    for model in _first_party_models():
        for field in _link_fields(model):
            label = _field_label(model, field)
            if isinstance(field, models.URLField):
                continue  # probed automatically unless skipped; either way accounted for
            if label not in known:
                missing.append(label)
    return missing


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
    if file_id is None or link.kind == "broken":
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


def enumerate_company_defaults(defaults: CompanyDefaults) -> list[OutboundLink]:
    """Every link or external id the singleton holds, one source per column.

    Fable: The same dispatch as every other row (``_row_links``), not a second
    one: an earlier copy indexed ``EXTERNAL_ID_FIELDS`` directly and would
    have raised on a singleton column filed as unverified. The singleton
    differs only in reporting an unset column as ``skipped: not configured``
    — configuration is expected to be set, a per-row NULL is not news.
    """
    labels = {
        field.name: _field_label(CompanyDefaults, field) for field in _link_fields(CompanyDefaults)
    }
    return [
        *_field_level_skips(labels),
        *_row_links(
            defaults,
            _row_level_fields(CompanyDefaults, labels),
            source=lambda name: f"CompanyDefaults.{name}",
            report_unset=True,
        ),
    ]


def _latest(model: type[models.Model], sample: int) -> models.QuerySet[models.Model]:
    names = {field.name for field in model._meta.concrete_fields}
    recency = next((name for name in _RECENCY_FIELDS if name in names), "pk")
    queryset = model._default_manager.order_by(f"-{recency}")
    return queryset if sample == 0 else queryset[:sample]


def _row_label(model: type[models.Model], row: models.Model) -> str:
    names = {field.name for field in model._meta.concrete_fields}
    label_field = next((name for name in _LABEL_FIELDS if name in names), "pk")
    return f"{model.__name__} {getattr(row, label_field)}"


def _derived_urls(label: str, row: models.Model) -> list[OutboundLink]:
    """Deep links the app builds from an id rather than storing."""
    if label != "xero.XeroPayRun.xero_id":
        return []
    from apps.timesheet.services.payroll_service import build_xero_payroll_url
    from apps.xero.models.xero_payroll import XeroPayRun

    if not isinstance(row, XeroPayRun):
        raise TypeError(f"{label} row is {type(row).__name__}")
    source = _row_label(XeroPayRun, row)
    if CompanyDefaults.get_solo().xero_shortcode is None:
        return [OutboundLink(kind="skipped", source=source, detail="xero_shortcode not configured")]
    return [classify_url(build_xero_payroll_url(row.xero_id), source=source)]


def _field_level_skips(labels: dict[str, str]) -> list[OutboundLink]:
    """One skipped row per column the probe knows about but does not verify."""
    skips: list[OutboundLink] = []
    for label in labels.values():
        if label in SKIPPED_URL_FIELDS:
            skips.append(
                OutboundLink(kind="skipped", source=label, detail=SKIPPED_URL_FIELDS[label])
            )
        elif label in UNVERIFIED_EXTERNAL_ID_FIELDS:
            skips.append(
                OutboundLink(
                    kind="skipped", source=label, detail=UNVERIFIED_EXTERNAL_ID_FIELDS[label]
                )
            )
    return skips


def _row_level_fields(model: type[models.Model], labels: dict[str, str]) -> list[tuple[str, str]]:
    """The (field name, label) pairs read from every sampled row of ``model``."""
    paired_ids = {
        GOOGLE_URL_ID_PAIRS[label] for label in labels.values() if label in GOOGLE_URL_ID_PAIRS
    }
    chosen: list[tuple[str, str]] = []
    for name, label in labels.items():
        if label in paired_ids:
            continue  # read alongside its URL column
        is_url = isinstance(model._meta.get_field(name), models.URLField)
        if (
            label in GOOGLE_URL_ID_PAIRS
            or label in EXTERNAL_ID_FIELDS
            or (is_url and label not in SKIPPED_URL_FIELDS)
        ):
            chosen.append((name, label))
    return chosen


def _constant(label: str) -> Callable[[str], str]:
    """A row's source is the same whichever column the link came from."""
    return lambda _name: label


def _row_links(
    row: models.Model,
    row_fields: list[tuple[str, str]],
    *,
    source: Callable[[str], str],
    report_unset: bool,
) -> list[OutboundLink]:
    """The links one row holds; ``source`` names the row (or, for the singleton, the column)."""
    links: list[OutboundLink] = []
    for name, label in row_fields:
        value = getattr(row, name)
        if label in GOOGLE_URL_ID_PAIRS:
            id_name = GOOGLE_URL_ID_PAIRS[label].rsplit(".", 1)[1]
            file_id = getattr(row, id_name)
            if value is None and file_id is None and not report_unset:
                continue
            pair_source = f"{source(name)}/_id" if report_unset else source(name)
            links.append(_google_pair(value, file_id, source=pair_source))
        elif value is None:
            if report_unset:
                links.append(
                    OutboundLink(kind="skipped", source=source(name), detail="not configured")
                )
        elif label in EXTERNAL_ID_FIELDS:
            links.append(
                OutboundLink(
                    kind=EXTERNAL_ID_FIELDS[label], source=source(name), external_id=str(value)
                )
            )
            links.extend(_derived_urls(label, row))
        else:
            links.append(classify_url(value, source=source(name)))
    return links


def enumerate_database_links(*, sample: int) -> list[OutboundLink]:
    """Per-row links from every first-party model, driven by the field registries.

    Google ids are checked on every row (cheap, pooled). Xero document ids
    are sampled: the deep-link templates are what can rot and the latest
    ``sample`` rows prove them; ``sample=0`` checks every row on an instance
    small enough to afford the per-call pacing.
    """
    missing = unclassified_fields()
    if missing:
        raise RuntimeError(
            "link-shaped columns not classified in outbound_links_probe: " + ", ".join(missing)
        )
    links: list[OutboundLink] = []
    for model in _first_party_models():
        if model is CompanyDefaults:
            continue  # the singleton has its own enumeration
        labels = {field.name: _field_label(model, field) for field in _link_fields(model)}
        links.extend(_field_level_skips(labels))
        row_fields = _row_level_fields(model, labels)
        if not row_fields:
            continue
        samples_xero = any(
            EXTERNAL_ID_FIELDS.get(label) in XERO_DOCUMENT_KINDS for _, label in row_fields
        )
        for row in _latest(model, sample if samples_xero else 0):
            links.extend(
                _row_links(
                    row, row_fields, source=_constant(_row_label(model, row)), report_unset=False
                )
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

#: Fable: The server identified the resource well enough to demand credentials
#: or another method — api.xero.com answers 401, a POST-only token endpoint
#: answers 400 — which is existence, the only thing an anonymous probe can
#: establish.
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
    def document_exists(self, kind: XeroDocumentKind, external_id: str) -> bool: ...


def verify_http(link: OutboundLink, *, fetch: HttpFetch) -> LinkVerdict:
    if link.url is None:
        raise ValueError(f"{link.source}: an http link needs a URL")
    try:
        status = fetch(link.url)
    # deliberate-swallow: both are the probe's own typed outcomes, raised by
    # the fetch adapter so that the verdict, not a traceback, carries them.
    except UnreachableError as exc:
        return LinkVerdict(link, "unreachable", str(exc))
    except NoSuchHostError as exc:
        return LinkVerdict(link, "broken", f"host does not resolve: {exc}")
    note = " (route probe; the web app cannot be authenticated)" if link.kind == "xero_web" else ""
    if 200 <= status < 400:
        return LinkVerdict(link, "ok", f"HTTP {status}{note}")
    if status in _ROUTED_STATUSES:
        return LinkVerdict(
            link, "ok", f"HTTP {status}: exists, needs credentials or another method"
        )
    return LinkVerdict(link, "broken", f"HTTP {status}{note}")


def verify_google_file(link: OutboundLink, *, lookup: GoogleLookup) -> LinkVerdict:
    if link.external_id is None:
        raise ValueError(f"{link.source}: a google_file link needs a file id")
    try:
        state = lookup(link.external_id)
    # deliberate-swallow: DriveLookup raises this when Drive itself could not
    # be asked (quota 403, 5xx, transport); that is a verdict that fails the
    # gate, not a traceback.
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
        return LinkVerdict(link, "broken", f"no access to file {link.external_id} as this identity")
    if state.trashed:
        return LinkVerdict(link, "broken", f"{state.name!r} is trashed")
    return LinkVerdict(link, "ok", state.name)


_XERO_DOCUMENT_KINDS_BY_NAME: dict[str, XeroDocumentKind] = {
    kind: kind for kind in get_args(XeroDocumentKind)
}


def _is_xero_document_kind(kind: str) -> XeroDocumentKind | None:
    return _XERO_DOCUMENT_KINDS_BY_NAME.get(kind)


def verify_xero(link: OutboundLink, *, xero: XeroLookups) -> LinkVerdict:
    if link.external_id is None:
        raise ValueError(f"{link.source}: a Xero link needs an external id")
    document_kind = _is_xero_document_kind(link.kind)
    try:
        if link.kind == "xero_tenant":
            present = link.external_id in xero.tenant_ids()
        elif link.kind == "xero_branding_theme":
            present = link.external_id in xero.branding_theme_ids()
        elif link.kind == "xero_payroll_calendar":
            present = link.external_id in xero.payroll_calendar_ids()
        elif document_kind is not None:
            present = xero.document_exists(document_kind, link.external_id)
        else:
            raise ValueError(f"{link.source}: {link.kind} is not a Xero kind")
    # deliberate-swallow: LiveXero raises this when the tenant listing or the
    # document fetch could not be made at all (no token, quota, transport);
    # that is a verdict that fails the gate, not a traceback.
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
#: Fable: errno values for which the resolver has ANSWERED "no such name";
#: EAI_AGAIN is "try later" and, offline, every host would otherwise read as
#: deleted.
_NO_SUCH_HOST_ERRNOS: frozenset[int] = frozenset({socket.EAI_NONAME, socket.EAI_NODATA})


_RESOLVER_ERRNO = re.compile(r"\[Errno (-?\d+)\]")


def _no_such_host(exc: BaseException) -> bool:
    """Whether a requests ConnectionError is the resolver saying the name does not exist.

    Fable: urllib3's ``NameResolutionError`` keeps the ``gaierror`` only as
    text in its message, so the errno is read back out of ``[Errno -2]``.
    """
    from urllib3.exceptions import MaxRetryError, NameResolutionError

    cause = exc.args[0] if exc.args else None
    if not isinstance(cause, MaxRetryError) or not isinstance(cause.reason, NameResolutionError):
        return False
    match = _RESOLVER_ERRNO.search(str(cause.reason))
    return match is not None and int(match.group(1)) in _NO_SUCH_HOST_ERRNOS


def requests_fetch(url: str) -> int:
    """Final status after redirects, by a streamed GET whose body is never read.

    Fable: Not HEAD: go.xero.com and payroll.xero.com answer 503 to every HEAD
    and portal.steelandtube.co.nz answers 404 to it, while GET discriminates
    on all three (measured 2026-08-22). A 429, a 5xx or a transport error is
    retried once so a single blip does not read as a finding; a second 429 is
    the host declining to answer, not a dead link.
    """
    import requests

    headers = {"User-Agent": _USER_AGENT}
    last: UnreachableError | None = None
    final = 0
    for _attempt in range(2):
        try:
            answer = requests.get(
                url, allow_redirects=True, timeout=_REQUEST_TIMEOUT, headers=headers, stream=True
            )
            answer.close()
        # deliberate-swallow: converted to the probe's typed outcomes — a
        # resolver "no such name" is a dead link, anything else is "could not
        # ask" and gets the one retry.
        except requests.ConnectionError as exc:
            if _no_such_host(exc):
                raise NoSuchHostError(urlsplit(url).hostname or url) from exc
            last = UnreachableError(f"{type(exc).__name__}: {exc}")
            continue
        except requests.RequestException as exc:
            last = UnreachableError(f"{type(exc).__name__}: {exc}")
            continue
        if answer.status_code == 429:
            last = UnreachableError("HTTP 429: rate limited twice; not a verdict on the link")
            continue
        if answer.status_code < 500:
            return answer.status_code
        last = None
        final = answer.status_code
    if last is not None:
        raise last
    return final


def google_credentials(identity: GoogleIdentity) -> Credentials:
    """Who asks Drive. Both answers are meaningful, so the operator chooses.

    Fable: ``delegated`` impersonates the Workspace user the app acts as
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


def google_identity_from_env() -> GoogleIdentity:
    """``PROBE_GOOGLE_AS`` for the integration test; a typo is an error, not the other identity."""
    value = os.environ.get("PROBE_GOOGLE_AS", "service-account")
    if value == "delegated":
        return "delegated"
    if value == "service-account":
        return "service-account"
    raise RuntimeError(f"PROBE_GOOGLE_AS must be 'delegated' or 'service-account', not {value!r}")


#: Drive 403 reasons that mean "asked too fast", not "not yours".
_DRIVE_QUOTA_REASONS: frozenset[str] = frozenset(
    {"userRateLimitExceeded", "rateLimitExceeded", "dailyLimitExceeded"}
)


def _drive_error_reasons(exc: HttpError) -> set[str]:
    """The ``reason`` codes in a Drive error body; empty unless the body is Google's JSON shape."""
    try:
        body = json.loads(exc.content.decode("utf-8"))
    # deliberate-swallow: a non-JSON body (an HTML error page from a proxy)
    # carries no reason codes, which the caller reports as such.
    except (UnicodeDecodeError, json.JSONDecodeError):
        return set()
    if not isinstance(body, dict) or not isinstance(body.get("error"), dict):
        return set()
    errors = body["error"].get("errors", [])
    if not isinstance(errors, list):
        return set()
    return {str(item["reason"]) for item in errors if isinstance(item, dict) and "reason" in item}


class _ThreadDrive(threading.local):
    drive: DriveResource | None = None


class DriveLookup:
    """``files.get`` with the given credentials, one Drive client per thread.

    Fable: googleapiclient discovery objects are not thread-safe — each owns
    an ``httplib2.Http``, and the library's own thread-safety guide says to
    build one per thread — so the credentials are built once and a client per
    worker thread is built from them on first use.
    """

    def __init__(self, *, credentials: Callable[[], Credentials]) -> None:
        self._local = _ThreadDrive()
        self._credentials_lock = threading.Lock()
        self._build_credentials = credentials
        self._credentials: Credentials | None = None

    def drive(self) -> DriveResource:
        from scripts.gdocs.gauth import build_drive

        if self._local.drive is not None:
            return self._local.drive
        with self._credentials_lock:
            if self._credentials is None:
                self._credentials = self._build_credentials()
        self._local.drive = build_drive(self._credentials)
        return self._local.drive

    def __call__(self, file_id: str) -> GoogleFileState:
        from googleapiclient.errors import HttpError

        try:
            found = (
                self.drive()
                .files()
                .get(fileId=file_id, supportsAllDrives=True, fields="id,name,trashed")
                .execute()
            )
        # deliberate-swallow: 404 and a permission 403 are the answers this
        # lookup exists to give; a quota 403 and anything else is Drive not
        # answering.
        except HttpError as exc:
            reasons = _drive_error_reasons(exc)
            if exc.status_code == 404:
                return GoogleFileState(status="missing")
            if exc.status_code == 403 and not reasons & _DRIVE_QUOTA_REASONS:
                return GoogleFileState(status="forbidden")
            raise UnreachableError(
                f"Drive answered {exc.status_code} for {file_id}: "
                f"{', '.join(sorted(reasons)) or exc.reason}"
            ) from exc
        except OSError as exc:
            raise UnreachableError(f"{type(exc).__name__}: {exc}") from exc
        return GoogleFileState(status="found", name=found["name"], trashed=found["trashed"])


class LiveXero:
    """The app's own Xero client, each listing fetched once per run."""

    def __init__(self) -> None:
        self._tenants: set[str] | None = None
        self._themes: set[str] | None = None
        self._calendars: set[str] | None = None

    def tenant_ids(self) -> set[str]:
        if self._tenants is None:
            from apps.xero.auth import connected_tenant_ids

            self._tenants = self._ask(connected_tenant_ids)
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

    def document_exists(self, kind: XeroDocumentKind, external_id: str) -> bool:
        return self._ask(lambda: self._document_rows(kind, external_id))

    @staticmethod
    def _document_rows(kind: XeroDocumentKind, external_id: str) -> bool:
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
            else:
                rows = [PayrollNzApi(get_api_client()).get_pay_run(tenant_id, external_id).pay_run]
        # deliberate-swallow: a 404 is the answer this function exists to
        # give; anything else propagates to _ask as "could not ask".
        except ApiException as exc:
            if exc.status == 404:
                return False
            raise
        return bool(rows)

    @staticmethod
    def _ask[T](call: Callable[[], T]) -> T:
        from xero_python.exceptions import ApiException

        try:
            return call()
        # deliberate-swallow: converted to the probe's typed "could not ask"
        # outcome; RuntimeError is how apps.xero.auth reports a missing or
        # unrefreshable token.
        except (ApiException, RuntimeError, OSError) as exc:
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


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _non_negative(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be 0 (every row) or a positive sample size")
    return number


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--workers", type=_positive, default=16, help="threads for HTTP and Drive lookups"
    )
    parser.add_argument(
        "--sample", type=_non_negative, default=5, help="latest N Xero documents per type; 0 = all"
    )
    parser.add_argument(
        "--kind", action="append", choices=LINK_KINDS, help="only these link kinds (repeatable)"
    )
    parser.add_argument(
        "--google-as",
        choices=get_args(GoogleIdentity),
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
    return 1 if report.broken or report.unreachable else 0


if __name__ == "__main__":
    sys.exit(main())
