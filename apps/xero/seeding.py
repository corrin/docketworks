"""Push a restored database into a non-production Xero org.

After a scrubbed production dump is restored into a dev/UAT instance, every
mirror id in the database (``Company.xero_contact_id``, ``Invoice.xero_id``,
the chart of accounts, ...) points at entities in the PRODUCTION Xero org that
do not exist in the connected demo org. Left alone, the first sync does not
recognise the local rows and creates duplicate companies, invoices and quotes.

This module re-points the mirror: clear the production ids, then link local
records to their demo-org counterparts where those exist and create them where
they do not. It is operator-run tooling (``manage.py seed_xero_from_database``)
and is deliberately loud — a seed that looks successful while records remain
unlinked is worse than a failed one, because the duplicates only appear on the
next sync.

Both "has the mirror been cleared?" and "is the batch finished?" are DERIVED
from the data, never remembered in a flag or an operator's choice of options:
``mirror_points_at_foreign_org`` reads whether any cleared-column link carries
a tenant other than the connected one, and ``seed_convergence`` counts the work
each phase would still do. An earlier design tracked both in command flags
(``--skip-clear``, a ``partial`` boolean derived from ``--only``), which made
the sync gate a memory of which options were typed rather than a statement
about the mirror.

Not reused from the normal push paths, and why:

- ``apps.xero.transforms.sync_accounts`` keys the chart of accounts on
  ``xero_id``, which is exactly the value the seed has to REWRITE; matching by
  name is the only join available across two orgs.
- ``apps.xero.documents.invoice.XeroInvoiceManager`` creates a NEW invoice for
  a job from current job state. The seed re-creates EXISTING invoices with
  their stored numbers, dates and line totals, AUTHORISED and in batches of 50.
"""

import logging
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.db.models import Q, QuerySet
from xero_python.accounting import AccountingApi, LineItem
from xero_python.accounting import Contact as XeroContact
from xero_python.accounting import Invoice as XeroInvoice
from xero_python.accounting import Quote as XeroQuote

from apps.accounting.models import Invoice, Quote
from apps.accounts.models import Staff
from apps.company.models import Company
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.purchasing.models import PurchaseOrder, Stock
from apps.timesheet.services import payroll_employee_sync
from apps.xero.auth import get_api_client, get_tenant_id
from apps.xero.contacts import contact_from_company
from apps.xero.helpers import clean_payload, convert_to_pascal_case, sanitize_for_xero
from apps.xero.models import XeroAccount, XeroPayItem, XeroSyncCursor
from apps.xero.operator_guards import assert_not_production_target, assert_xero_writes_enabled
from apps.xero.payroll_employees import ensure_employee_leave_types, missing_employee_leave_types
from apps.xero.payroll_sync import pay_items_needing_relink, sync_xero_pay_items
from apps.xero.stock_sync import stock_pending_sync, sync_all_local_stock_to_xero
from apps.xero.sync import ENTITY_CONFIGS, _resolve_api_method
from apps.xero.transforms import process_xero_data

logger = logging.getLogger(__name__)

# The same floor apps/xero/sync.get_last_modified_time returns for an empty
# mirror: a cursor at this value makes the next sync's if_modified_since
# predate every record in any Xero org, i.e. a full pull.
_SYNC_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)

# Xero's documented maximum for a batch create on these endpoints.
BATCH_SIZE = 50
# Page size for paged reads; a shorter page means the last page.
LOOKUP_PAGE_SIZE = 100
# The account every seeded invoice and quote line is coded to. The seed
# re-creates documents whose original line coding is not in the backup.
SALES_ACCOUNT_NAME = "Sales"


@dataclass(frozen=True)
class XeroContactRef:
    """The two fields of a Xero contact the by-name linker needs."""

    name: str
    contact_id: str


@dataclass(frozen=True)
class SeedContactsResult:
    """Contacts phase outcome."""

    linked: int
    created: int


@dataclass(frozen=True)
class SeedAccountsResult:
    """Chart-of-accounts phase outcome."""

    updated: int
    created: int


@dataclass(frozen=True)
class SeedDocumentsResult:
    """Invoice or quote phase outcome."""

    created: int
    linked: int
    orphans_deleted: int
    skipped_no_contact: int


@dataclass(frozen=True)
class ClearedIdsResult:
    """Per-column row counts the clear phase nulled or deleted."""

    cleared: dict[str, int] = field(default_factory=dict)


# --- Contacts ---------------------------------------------------------------


def companies_needing_contacts() -> list[Company]:
    """Companies that must exist in the target org before documents can be seeded.

    Every company reached by a job, a job-linked invoice or a job-linked quote,
    plus the configured test company — E2E and manual Xero testing drive that
    one, so an installation whose test company is absent from the target org
    has a broken test path, not a smaller seed.

    Jobs alone was the earlier scope and under-delivered this docstring:
    ``Invoice.company``/``Quote.company`` are separate columns from
    ``job.client``, so a restored document can bill a company that holds no
    jobs of its own. The document phases skip such a document for want of a
    contact id, and the contacts phase never picked the company up — the two
    predicates disagreed and the seed could not converge.
    """
    defaults = CompanyDefaults.get_solo()
    if not defaults.test_company_name:
        raise ValueError(
            "CompanyDefaults.test_company_name is not set. It is required for Xero sync testing."
        )
    test_company = Company.objects.filter(name=defaults.test_company_name).first()
    if test_company is None:
        raise ValueError(
            f"Test company '{defaults.test_company_name}' not found in the database. "
            "Ensure the test company exists before seeding Xero."
        )

    company_ids = set(
        Company.objects.filter(
            Q(xero_contact_id__isnull=True)
            & (Q(jobs__isnull=False) | Q(invoice__job__isnull=False) | Q(quote__job__isnull=False))
        )
        .distinct()
        .values_list("id", flat=True)
    )
    if not test_company.xero_contact_id:
        company_ids.add(test_company.id)

    return list(Company.objects.filter(id__in=company_ids))


def get_all_xero_contacts() -> list[XeroContactRef]:
    """Fetch every contact in the connected org, archived ones included."""
    accounting_api = AccountingApi(get_api_client())
    response = accounting_api.get_contacts(get_tenant_id(), include_archived=True)

    contacts: list[XeroContactRef] = []
    for contact in response.contacts or []:
        if not contact.name or not contact.contact_id:
            raise ValueError(f"Xero returned a contact without a name or id: {contact}")
        contacts.append(XeroContactRef(name=contact.name, contact_id=contact.contact_id))

    logger.info("Fetched %d contacts from Xero", len(contacts))
    return contacts


def bulk_create_contacts_in_xero(companies: Sequence[Company]) -> int:
    """Create companies as Xero contacts in batches; returns the created count."""
    if not companies:
        return 0

    accounting_api = AccountingApi(get_api_client())
    tenant_id = get_tenant_id()
    total_created = 0

    for start in range(0, len(companies), BATCH_SIZE):
        batch = list(companies[start : start + BATCH_SIZE])
        batch_number = start // BATCH_SIZE + 1

        contact_batch = []
        for company in batch:
            if not company.validate_for_xero():
                raise ValueError(f"Company {company.name} failed Xero validation")
            contact_batch.append(contact_from_company(company))

        logger.info("Creating batch %d of %d contacts in Xero", batch_number, len(contact_batch))
        response = accounting_api.create_contacts(tenant_id, contacts={"contacts": contact_batch})

        if not response.contacts:
            raise ValueError(f"Xero API returned empty response for contact batch {batch_number}")

        # Mapped back by SUBMISSION ORDER — Xero's create_contacts response
        # carries no client-supplied key. The name check is the tripwire: if
        # Xero ever stops preserving order, pairing ids with the wrong
        # companies would corrupt the mirror silently.
        for position, (company, created_contact) in enumerate(
            zip(batch, response.contacts, strict=True)
        ):
            if created_contact.name != company.name:
                raise ValueError(
                    f"Xero response order mismatch at position {position}: sent "
                    f"{company.name!r} but received {created_contact.name!r}. Xero is no "
                    f"longer preserving batch submission order; verify with a small "
                    f"live batch before re-running the seed."
                )
            if not created_contact.contact_id:
                raise ValueError(f"Xero created contact {company.name!r} without a contact id")
            company.xero_contact_id = created_contact.contact_id
            # The tenant is written with the id, never separately: an id with
            # no tenant cannot be attributed to an org, so "is this link ours?"
            # stops being answerable from the row.
            company.xero_tenant_id = tenant_id
            company.save(update_fields=["xero_contact_id", "xero_tenant_id"])
            total_created += 1
            logger.info(
                "Created Xero contact for company %s: %s", company.name, company.xero_contact_id
            )

    return total_created


def seed_companies_to_xero(companies: Iterable[Company]) -> SeedContactsResult:
    """Link companies to existing Xero contacts by name; create the remainder."""
    tenant_id = get_tenant_id()
    existing_contacts = get_all_xero_contacts()

    # Multimap: one Xero name can map to several contact ids (Xero allows
    # duplicate contact names). Local companies with shared names are
    # legitimate — different real customers — and each must claim a DISTINCT
    # contact id, because the local column is unique-constrained.
    existing_by_name: defaultdict[str, list[str]] = defaultdict(list)
    for contact in existing_contacts:
        existing_by_name[contact.name.lower()].append(contact.contact_id)

    companies_to_link: list[tuple[Company, str]] = []
    companies_to_create: list[Company] = []

    for company in companies:
        candidates = existing_by_name.get(company.name.lower())
        if candidates:
            # Pop the claimed candidate so a second local company with the
            # same name cannot race onto the same contact id; it falls
            # through to creation instead.
            companies_to_link.append((company, candidates.pop(0)))
        else:
            companies_to_create.append(company)

    for company, existing_contact_id in companies_to_link:
        company.xero_contact_id = existing_contact_id
        company.xero_tenant_id = tenant_id
        company.save(update_fields=["xero_contact_id", "xero_tenant_id"])
        logger.info(
            "Linked company %s to existing Xero contact %s", company.name, existing_contact_id
        )

    created = bulk_create_contacts_in_xero(companies_to_create)
    return SeedContactsResult(linked=len(companies_to_link), created=created)


# --- Idempotence lookups ----------------------------------------------------


def _lookup_page(
    entity_name: str,
    items: list[Any],
    key_func: Callable[[Any], str | None],
    value_func: Callable[[Any], str | None],
) -> dict[str, str]:
    """Map one page of Xero entities to ``{key: value}``, skipping unkeyed ones."""
    page: dict[str, str] = {}
    for item in items:
        key = key_func(item)
        if not key:
            continue
        value = value_func(item)
        if value is None:
            # A keyed entity Xero names no id for cannot be claimed by the
            # linker, so the seed would create a duplicate alongside it.
            # Malformed remote data fails the read (ADR 0015).
            raise ValueError(f"Xero {entity_name} {key!r} carries no id")
        page[key] = value
    return page


def fetch_xero_entity_lookup(
    entity_name: str,
    key_func: Callable[[Any], str | None],
    value_func: Callable[[Any], str | None],
) -> dict[str, str]:
    """Fetch every entity of a type from Xero as ``{key: value}``.

    Reuses ENTITY_CONFIGS for API-method resolution, pagination mode and
    params so the seed reads Xero exactly the way the sync engine does. The
    ``Any`` in the callbacks is the SDK seam: ENTITY_CONFIGS keys a different
    untyped SDK model per entity, and each call site immediately narrows to
    the two fields it reads.
    """
    xero_type, _, _, api_method, _, config_params, pagination_mode = ENTITY_CONFIGS[entity_name]
    api_func = _resolve_api_method(api_method)

    params: dict[str, Any] = {"xero_tenant_id": get_tenant_id()}
    if pagination_mode == "page":
        params["page_size"] = LOOKUP_PAGE_SIZE
    if config_params:
        params.update(config_params)

    lookup: dict[str, str] = {}
    page = 1
    while True:
        if pagination_mode == "page":
            params["page"] = page

        entities = api_func(**params)
        if entities is None:
            raise ValueError(f"API returned None for {entity_name}")

        items = entities if isinstance(entities, list) else getattr(entities, xero_type)
        if not items:
            break

        lookup.update(_lookup_page(entity_name, items, key_func, value_func))

        logger.info("Fetched %d %s (total: %d)", len(items), entity_name, len(lookup))

        if len(items) < LOOKUP_PAGE_SIZE or pagination_mode != "page":
            break
        page += 1

    return lookup


# --- Chart of accounts ------------------------------------------------------


def seed_accounts_from_xero() -> SeedAccountsResult:
    """Re-point local XeroAccount rows at the target org's account ids.

    Upserts BY NAME, not by ``xero_id``: the ids in the backup belong to the
    production org, and the name is the only value shared across the two.
    """
    local_count = XeroAccount.objects.count()
    logger.info("Found %d XeroAccount records from the backup", local_count)
    if local_count == 0:
        # No local chart of accounts means no restore has happened; fetching
        # would invent rows the rest of the seed does not expect.
        return SeedAccountsResult(updated=0, created=0)

    tenant_id = get_tenant_id()
    accounting_api = AccountingApi(get_api_client())
    response = accounting_api.get_accounts(tenant_id)
    xero_accounts = response.accounts or []
    logger.info("Fetched %d accounts from the target Xero org", len(xero_accounts))

    updated = 0
    created = 0
    for account in xero_accounts:
        # updated_date_utc joins the guard because xero_last_modified is NOT
        # NULL: the stub used to declare it Any, which let a None through to
        # an IntegrityError deep in the loop instead of naming the payload.
        if account.account_id is None or account.name is None or account.updated_date_utc is None:
            raise ValueError(
                "Xero account payload missing id, name or updated_date_utc "
                f"(id={account.account_id!r})"
            )
        _row, was_created = XeroAccount.objects.update_or_create(
            account_name=account.name,
            defaults={
                "xero_id": account.account_id,
                "xero_tenant_id": tenant_id,
                "account_code": account.code or None,
                "description": account.description or None,
                # .value, not str(): the SDK deserialises type as an
                # AccountType enum, and str() persists "AccountType.BANK".
                "account_type": account.type.value if account.type else None,
                "tax_type": account.tax_type or None,
                "enable_payments": bool(account.enable_payments_to_account),
                "xero_last_modified": account.updated_date_utc,
                # A never-synced marker only — nothing reads it to drive a
                # pull; the full re-pull is forced by the epoch cursor reset
                # in clear_production_xero_ids.
                "xero_last_synced": None,
                "raw_json": process_xero_data(account),
            },
        )
        if was_created:
            created += 1
        else:
            updated += 1

    logger.info("Accounts re-pointed: %d updated, %d created", updated, created)
    return SeedAccountsResult(updated=updated, created=created)


# --- Invoices and quotes ----------------------------------------------------


def invoice_line_unit_amount(
    quantity: Decimal, line_amount_excl_tax: Decimal | None, unit_price: Decimal | None
) -> Decimal:
    """Return a unit amount consistent with Xero's Exclusive line totals.

    Xero recomputes the line total as quantity x unit amount, so the stored
    unit price cannot be sent as-is when it disagrees with the stored line
    total (rounding, discounts): the seeded invoice would not match the
    restored one. Four decimal places is Xero's precision for unit amounts.
    """
    if line_amount_excl_tax is not None and quantity != 0:
        return (line_amount_excl_tax / quantity).quantize(Decimal("0.0000"), rounding=ROUND_HALF_UP)
    if unit_price is not None:
        return unit_price
    return Decimal("0.0000")


def sales_account_code() -> str:
    """Return the account code every seeded invoice and quote line is coded to.

    Public because the pre-seed restore check (scripts/ops/restore_checks/
    check_xero_accounts.py) gates on exactly this rule and prints the refusal
    as its FAIL text; a second statement of the rule there drifted from this
    one (ADR 0039).

    Refuses a missing account, or a NULL or blank code, rather than passing it
    through: Xero accepts a line with no account code and files it as uncoded,
    so the seed would finish successfully having shipped an entire ledger of
    documents nobody can report on, and the repair is re-creating them.
    """
    account = XeroAccount.objects.filter(account_name=SALES_ACCOUNT_NAME).first()
    if account is None:
        raise ValueError(
            f"No XeroAccount named '{SALES_ACCOUNT_NAME}'. Every seeded invoice and quote "
            f"line is coded to that account, so the seed cannot run without it."
        )
    if not account.account_code:
        raise ValueError(
            f"The '{SALES_ACCOUNT_NAME}' account (XeroAccount {account.xero_id}) has no "
            f"account_code, and every seeded invoice and quote line is coded to it. Set "
            f"its code to the target organisation's sales revenue code (200 in Xero's "
            f"default chart of accounts), then re-run the seed."
        )
    return account.account_code


def _job_description(job: Job) -> str:
    """Describe the job the way the seeded summary line reads."""
    description = f"Job: {job.job_number}"
    if job.description:
        description += f" - {sanitize_for_xero(job.description)}"
    return description


def _numbered_documents[TDocument: (Invoice, Quote)](
    documents: Sequence[TDocument],
) -> list[tuple[str, TDocument]]:
    """Pair each document with its number, refusing any that lack one.

    Batch responses are keyed on the document number; ``Quote.number`` is
    nullable and an invoice number can be blank, so a missing one would
    otherwise surface as an unmappable response AFTER the documents already
    exist in Xero.
    """
    unnumbered = [str(document.id) for document in documents if not document.number]
    if unnumbered:
        raise ValueError(
            f"Cannot seed {len(unnumbered)} job-linked document(s) with no document number: "
            f"{unnumbered}. Fix the source rows; the Xero batch response is keyed on it."
        )
    return [(str(document.number), document) for document in documents]


def _build_invoice_payload(invoice: Invoice, account_code: str) -> dict[str, Any]:
    """Build the Xero create payload for one restored invoice."""
    if invoice.job is None:
        raise ValueError(f"Invoice {invoice.number} has no job and must not be seeded")

    line_items = []
    for line in invoice.line_items.all():
        # Zero AND null coerce to 1 (v1's `li.quantity or 1`). Xero recomputes
        # a line total as quantity x unit amount, so a zero-quantity line must
        # ship as 1 x the stored line total; sending quantity 0 makes Xero
        # total the line at 0 and the seeded document silently under-totals
        # against the restored ledger.
        quantity = line.quantity or Decimal("1")
        line_items.append(
            LineItem(
                description=sanitize_for_xero(line.description),
                quantity=float(quantity),
                unit_amount=float(
                    invoice_line_unit_amount(
                        quantity=quantity,
                        line_amount_excl_tax=line.line_amount_excl_tax,
                        unit_price=line.unit_price,
                    )
                ),
                line_amount=(
                    float(line.line_amount_excl_tax)
                    if line.line_amount_excl_tax is not None
                    else None
                ),
                # `is not None`, not truthiness: a legitimate 0.00 tax line
                # sent as None makes Xero apply the account's default tax
                # rate, diverging the seeded totals from the restored ledger.
                tax_amount=float(line.tax_amount) if line.tax_amount is not None else None,
                account_code=account_code,
            )
        )

    if not line_items:
        line_items.append(
            LineItem(
                description=_job_description(invoice.job),
                quantity=1,
                unit_amount=float(invoice.total_excl_tax),
                account_code=account_code,
            )
        )

    xero_invoice = XeroInvoice(
        type="ACCREC",
        contact=XeroContact(contact_id=invoice.company.xero_contact_id, name=invoice.company.name),
        line_items=line_items,
        date=invoice.date.isoformat(),
        due_date=invoice.due_date.isoformat() if invoice.due_date else None,
        line_amount_types="Exclusive",
        currency_code="NZD",
        # AUTHORISED, not DRAFT: the restored invoices are issued documents,
        # and a draft in Xero would not reconcile against the local ledger.
        status="AUTHORISED",
        invoice_number=invoice.number,
        reference=invoice.job.order_number,
    )
    payload: dict[str, Any] = convert_to_pascal_case(clean_payload(xero_invoice.to_dict()))
    return payload


def _build_quote_payload(quote: Quote, account_code: str) -> dict[str, Any]:
    """Build the Xero create payload for one restored quote."""
    if quote.job is None:
        raise ValueError(f"Quote {quote.number} has no job and must not be seeded")

    xero_quote = XeroQuote(
        contact=XeroContact(contact_id=quote.company.xero_contact_id, name=quote.company.name),
        # One summary line: a quote's local detail lives in the job's cost
        # sets, not in stored Xero line items.
        line_items=[
            LineItem(
                description=_job_description(quote.job),
                quantity=1,
                unit_amount=float(quote.total_excl_tax),
                account_code=account_code,
            )
        ],
        date=quote.date.isoformat(),
        line_amount_types="Exclusive",
        currency_code="NZD",
        status="DRAFT",
        quote_number=quote.number,
        reference=quote.job.order_number,
    )
    payload: dict[str, Any] = convert_to_pascal_case(clean_payload(xero_quote.to_dict()))
    return payload


def _create_invoices_in_xero(
    accounting_api: AccountingApi, tenant_id: str, payloads: list[dict[str, Any]]
) -> list[Any] | None:
    """Send one invoice batch; return the documents Xero echoed back."""
    return accounting_api.create_invoices(tenant_id, invoices={"Invoices": payloads}).invoices


def _create_quotes_in_xero(
    accounting_api: AccountingApi, tenant_id: str, payloads: list[dict[str, Any]]
) -> list[Any] | None:
    """Send one quote batch; return the documents Xero echoed back."""
    return accounting_api.create_quotes(tenant_id, quotes={"Quotes": payloads}).quotes


@dataclass(frozen=True)
class _DocumentKind[TDocument: (Invoice, Quote)]:
    """Everything seeding invoices and seeding quotes genuinely disagree on.

    The control flow is one implementation (``seed_documents``). It was two
    near-identical copies until they drifted — the invoice copy marked linked
    rows never-synced and the quote copy did not — which is the failure mode
    this shape removes. A boolean "is this quotes?" inside one function was
    rejected: it re-creates the two bodies inside the merged one.

    ``Any`` is the SDK seam, as in ``fetch_xero_entity_lookup``: the response
    model differs per entity and each callback immediately narrows to the one
    field it reads.
    """

    model: type[TDocument]
    entity: str
    remote_number: Callable[[Any], str | None]
    remote_id: Callable[[Any], str | None]
    build_payload: Callable[[TDocument, str], dict[str, Any]]
    create: Callable[[AccountingApi, str, list[dict[str, Any]]], list[Any] | None]

    def pending(self, tenant_id: str) -> list[TDocument]:
        """Job-linked documents the connected org has not claimed yet."""
        return list(
            self.model.objects.filter(job__isnull=False)
            .exclude(xero_tenant_id=tenant_id)
            .select_related("job", "company")
        )

    def orphans(self) -> QuerySet[TDocument]:
        """Documents with no job: restored remnants that must not be seeded."""
        return self.model.objects.filter(job__isnull=True)

    def claim(self, document: TDocument, xero_id: str, tenant_id: str) -> None:
        """Point one local row at its document in the connected org."""
        document.xero_id = xero_id
        document.xero_tenant_id = tenant_id
        update_fields = ["xero_id", "xero_tenant_id", *self._never_synced_fields(document)]
        document.save(update_fields=update_fields)

    def _never_synced_fields(self, document: TDocument) -> list[str]:
        """Null ``xero_last_synced`` where the column allows it, and name it.

        A never-synced marker only — nothing reads it to drive a pull; the full
        re-pull is forced by the epoch cursor reset in
        ``clear_production_xero_ids``. Read off the column rather than declared
        per kind: ``Quote.xero_last_synced`` is NOT NULL, so nulling both
        unconditionally IntegrityErrors every seeded quote, and a per-kind flag
        would be free to disagree with the schema it describes.
        """
        field = self.model._meta.get_field("xero_last_synced")
        if not field.null:
            return []
        # setattr, not `document.xero_last_synced = None`: this body is
        # type-checked once per constraint of TDocument, and the Quote pass
        # rejects None for its non-nullable column even though the guard above
        # makes that branch unreachable for quotes.
        setattr(document, field.name, None)
        return [field.name]


INVOICES = _DocumentKind(
    model=Invoice,
    entity="invoices",
    remote_number=lambda invoice: invoice.invoice_number,
    remote_id=lambda invoice: invoice.invoice_id,
    build_payload=_build_invoice_payload,
    create=_create_invoices_in_xero,
)

QUOTES = _DocumentKind(
    model=Quote,
    entity="quotes",
    remote_number=lambda quote: quote.quote_number,
    remote_id=lambda quote: quote.quote_id,
    build_payload=_build_quote_payload,
    create=_create_quotes_in_xero,
)


def seed_documents[TDocument: (Invoice, Quote)](
    kind: _DocumentKind[TDocument],
) -> SeedDocumentsResult:
    """Delete orphaned documents, then link or re-create job-linked ones."""
    orphans_deleted, _ = kind.orphans().delete()
    if orphans_deleted:
        logger.info("Deleted %d orphaned %s (no job link)", orphans_deleted, kind.entity)

    tenant_id = get_tenant_id()
    pending = kind.pending(tenant_id)
    if not pending:
        return SeedDocumentsResult(
            created=0, linked=0, orphans_deleted=orphans_deleted, skipped_no_contact=0
        )

    to_seed = [document for document in pending if document.company.xero_contact_id]
    skipped_no_contact = len(pending) - len(to_seed)
    if skipped_no_contact:
        logger.warning(
            "Skipping %d %s whose company has no xero_contact_id - run contacts first",
            skipped_no_contact,
            kind.entity,
        )
    if not to_seed:
        return SeedDocumentsResult(
            created=0,
            linked=0,
            orphans_deleted=orphans_deleted,
            skipped_no_contact=skipped_no_contact,
        )

    numbered = _numbered_documents(to_seed)

    existing = fetch_xero_entity_lookup(kind.entity, kind.remote_number, kind.remote_id)
    logger.info("Found %d existing %s in the target Xero org", len(existing), kind.entity)

    linked = 0
    to_create: list[tuple[str, TDocument]] = []
    for number, document in numbered:
        existing_id = existing.get(number)
        if not existing_id:
            to_create.append((number, document))
            continue
        kind.claim(document, existing_id, tenant_id)
        linked += 1
        logger.info(
            "Linked existing %s %s (%s)", kind.entity, document.number, document.company.name
        )

    created = _batch_create(kind, to_create, tenant_id)
    return SeedDocumentsResult(
        created=created,
        linked=linked,
        orphans_deleted=orphans_deleted,
        skipped_no_contact=skipped_no_contact,
    )


def _batch_create[TDocument: (Invoice, Quote)](
    kind: _DocumentKind[TDocument], documents: list[tuple[str, TDocument]], tenant_id: str
) -> int:
    """Create documents in Xero in batches; map the response back by number."""
    if not documents:
        return 0

    accounting_api = AccountingApi(get_api_client())
    account_code = sales_account_code()
    by_number = dict(documents)
    created = 0

    for start in range(0, len(documents), BATCH_SIZE):
        batch = documents[start : start + BATCH_SIZE]
        batch_number = start // BATCH_SIZE + 1
        payloads = [kind.build_payload(document, account_code) for _number, document in batch]

        logger.info("Sending batch %d of %d %s", batch_number, len(payloads), kind.entity)
        remote_documents = kind.create(accounting_api, tenant_id, payloads)
        if not remote_documents:
            raise ValueError(f"Empty response from Xero for {kind.entity} batch {batch_number}")

        for remote in remote_documents:
            # A response with no number at all is the same failure as an
            # unrecognised one: nothing to map it back to.
            local = by_number.get(kind.remote_number(remote) or "")
            if local is None:
                # Not a warning: the local document stays unlinked, and the
                # next sync then creates a duplicate — the corruption this
                # command exists to prevent.
                raise ValueError(
                    f"Xero returned {kind.entity} numbered "
                    f"{kind.remote_number(remote)!r}, which could not be mapped back to a "
                    f"local record. Xero renumbered a submitted document, so the "
                    f"{kind.entity} already created in this batch are linked and the rest "
                    f"are not. Re-running as-is renumbers it again: delete the renumbered "
                    f"document in Xero and fix the clashing local number (Xero renumbers a "
                    f"number it already holds), then re-run the seed; it links what exists "
                    f"and creates only the remainder."
                )
            remote_id = kind.remote_id(remote)
            if not remote_id:
                raise ValueError(f"Xero response missing the {kind.entity} id for {local.number}")
            kind.claim(local, remote_id, tenant_id)
            created += 1
            logger.info("Seeded %s %s (%s)", kind.entity, local.number, local.company.name)

    return created


# --- Phase 0: clear the production ids --------------------------------------


def mirror_points_at_foreign_org(tenant_id: str) -> bool:
    """Whether any cleared-column link belongs to an org other than the connected one.

    This is the whole "does the clear need to run?" question, answered from the
    data. ``.exclude()`` on a nullable column keeps NULL rows, which is what
    makes it fire on a fresh restore: the production ids are present and the
    tenant columns are NULL, so nothing attributes them to this org.

    Only Company and XeroPayItem are consulted, because they are the two
    cleared columns that carry a tenant AND are never legitimately foreign
    mid-batch:

    - ``Job.xero_project_id`` and ``Stock.xero_id`` have no tenant column at
      all, so a stale link there is invisible here. Accepted residual: a real
      restore always carries production company ids too, which trips the
      Company signal, and a database that somehow held only stale stock ids
      would need the columns before it could be detected.
    - Invoice and Quote ``xero_tenant_id`` is legitimately foreign for every
      document the current run has not reached yet, so reading them here would
      report "needs clearing" throughout a normal run and re-clear on re-entry.
    """
    return (
        Company.objects.filter(xero_contact_id__isnull=False)
        .exclude(xero_tenant_id=tenant_id)
        .exists()
        or XeroPayItem.objects.filter(xero_id__isnull=False)
        .exclude(xero_tenant_id=tenant_id)
        .exists()
    )


def clear_production_xero_ids() -> ClearedIdsResult:
    """Null every mirror id that points at the production Xero org.

    ORM rather than v1's raw SQL with information_schema probes: those existed
    because v1's schema was still churning, and a missing column is now a
    migration defect that must fail loudly rather than be skipped.

    Invoice and Quote ``xero_id`` are NOT NULL and cannot be cleared here;
    ``seed_documents`` handles them by deleting orphans and
    re-creating job-linked documents in the target org.

    Closing the sync gate is the FIRST statement, not the caller's follow-up:
    from the moment the first id is nulled the mirror cannot be synced without
    creating duplicates, so the code that makes it unsyncable is the code that
    says so. A mid-clear crash therefore leaves the gate closed.
    """
    CompanyDefaults.set_xero_sync_enabled(enabled=False)

    cleared = {
        # Both columns together, and the filter matches either: a tenant claim
        # with no id is a data-model lie, so a row carrying only one of the
        # pair still has to be cleared.
        "company.xero_contact_id": Company.objects.filter(
            Q(xero_contact_id__isnull=False) | Q(xero_tenant_id__isnull=False)
        ).update(xero_contact_id=None, xero_tenant_id=None),
        "job.xero_project_id": Job.objects.filter(xero_project_id__isnull=False).update(
            xero_project_id=None
        ),
        "purchaseorder.xero_id": PurchaseOrder.objects.filter(
            Q(xero_id__isnull=False) | Q(xero_tenant_id__isnull=False)
        ).update(xero_id=None, xero_tenant_id=None),
        "stock.xero_id": Stock.objects.filter(xero_id__isnull=False).update(xero_id=None),
        "xeropayitem.xero_id": XeroPayItem.objects.filter(xero_id__isnull=False).update(
            xero_id=None, xero_tenant_id=None
        ),
        # v1 left the cursors in place. They are high-water marks against the
        # PRODUCTION org, so the first sync against the demo org skips every
        # record older than them. Reset to epoch, NOT deleted: an absent
        # cursor falls back to max(xero_last_modified) — the same stale
        # prod-era high-water mark — so deletion changed nothing and linked
        # documents kept their prod payloads indefinitely. An epoch cursor is
        # the one value get_sync_cursor actually honours that forces the next
        # sync to pull the target org in full.
        "xerosynccursor (reset to epoch)": XeroSyncCursor.objects.all().update(
            last_modified=_SYNC_EPOCH
        ),
    }

    # Staff.xero_user_id is deliberately preserved: it records which staff were
    # linked in production and is the crash-recovery marker the (Phase 4)
    # employee phase reads to know what to re-link.
    logger.info("Cleared production Xero ids: %s", cleared)
    return ClearedIdsResult(cleared=cleared)


# --- Convergence: how much work is left, measured from the data --------------


@dataclass(frozen=True)
class SeedConvergence:
    """What every seed phase would still do if it ran again.

    Each count is produced by the SAME predicate its phase works from, so
    "nothing left" cannot disagree with "nothing done". A count derived
    independently — a tally the phases increment, or a flag a finished run
    sets — is free to drift from the work, and then the sync gate opens over a
    mirror that is still half-linked.
    """

    companies_without_contacts: int
    invoices_pending: int
    quotes_pending: int
    stock_pending: int
    pay_items_pending: int
    staff_pending: int

    @property
    def remaining(self) -> dict[str, int]:
        """The non-zero counts, keyed by the phase name that clears them."""
        counts = {
            "contacts": self.companies_without_contacts,
            "employees": self.staff_pending,
            "invoices": self.invoices_pending,
            "quotes": self.quotes_pending,
            "stock": self.stock_pending,
            "pay items": self.pay_items_pending,
        }
        return {phase: count for phase, count in counts.items() if count}

    @property
    def converged(self) -> bool:
        """Whether the mirror is fully linked to the connected organisation."""
        return not self.remaining


def seed_convergence(tenant_id: str) -> SeedConvergence:
    """Measure the remaining seed work against the connected organisation."""
    linked_staff = Staff.objects.filter(
        xero_tenant_id=tenant_id,
        xero_user_id__isnull=False,
    ).exclude(xero_user_id="")
    payroll_not_ready = sum(
        bool(missing_employee_leave_types(str(staff.xero_user_id))) for staff in linked_staff
    )
    return SeedConvergence(
        companies_without_contacts=len(companies_needing_contacts()),
        # Orphans count as pending: the invoice phase deletes them, so a run
        # that left them has not finished even though nothing is unlinked.
        invoices_pending=len(INVOICES.pending(tenant_id)) + INVOICES.orphans().count(),
        quotes_pending=len(QUOTES.pending(tenant_id)) + QUOTES.orphans().count(),
        stock_pending=stock_pending_sync().count(),
        pay_items_pending=pay_items_needing_relink(tenant_id).count(),
        # Staff carrying an employee id stamped with another organisation, or
        # with no organisation at all — the shape a restored production dump
        # arrives in. Without this count the seed converged and opened the
        # sync gate over a mirror whose every staff link was a dead
        # production id, and the only symptom was payroll refusing to post.
        staff_pending=len(payroll_employee_sync.staff_needing_seed(tenant_id)) + payroll_not_ready,
    )


# --- The operator entry point -----------------------------------------------


@dataclass(frozen=True)
class SeedRunOutcome:
    """What one seed run did, and where it left the mirror."""

    cleared: ClearedIdsResult | None
    convergence: SeedConvergence
    gate_opened: bool


def _clear_phase(
    tenant_id: str, *, dry_run: bool, report: Callable[[str], None]
) -> ClearedIdsResult | None:
    """Clear the production ids if the mirror still points at a foreign org."""
    if not mirror_points_at_foreign_org(tenant_id):
        report("Mirror already linked to this organisation - nothing to clear")
        return None
    if dry_run:
        report("Mirror is linked to a different organisation - would clear the production ids")
        return None

    report("Mirror is linked to a different organisation - clearing...")
    cleared = clear_production_xero_ids()
    for column, count in cleared.cleared.items():
        report(f"  {column}: {count}")
    report("  staff.xero_user_id: preserved (crash-recovery marker)")
    return cleared


def _accounts_phase(*, dry_run: bool, report: Callable[[str], None]) -> None:
    report("Syncing the chart of accounts...")
    if dry_run:
        report("  would re-point local XeroAccount rows by account name")
        return
    result = seed_accounts_from_xero()
    report(f"  accounts: {result.updated} updated, {result.created} created")


def _contacts_phase(*, dry_run: bool, report: Callable[[str], None]) -> None:
    report("Syncing contacts...")
    companies = companies_needing_contacts()
    report(f"  {len(companies)} companies need a Xero contact id")
    if dry_run:
        for company in companies[:10]:
            report(f"  would process: {company.name}")
        if len(companies) > 10:
            report(f"  ... and {len(companies) - 10} more")
        return
    if not companies:
        return
    result = seed_companies_to_xero(companies)
    report(f"  contacts: {result.linked} linked, {result.created} created")


def _pay_items_phase(tenant_id: str, *, dry_run: bool, report: Callable[[str], None]) -> None:
    """Re-link the pay items jobs and cost lines reference to the connected org."""
    report("Re-syncing pay items against the target organisation...")
    if dry_run:
        pending = pay_items_needing_relink(tenant_id).count()
        report(f"  would re-link {pending} referenced pay items")
        return
    pay_items = sync_xero_pay_items()
    report(f"  pay items touched: {pay_items['records_updated']}")


def _employees_phase(tenant_id: str, *, dry_run: bool, report: Callable[[str], None]) -> None:
    """Re-link Staff to payroll employees in the connected organisation.

    The clear phase deliberately leaves ``Staff.xero_user_id`` alone, so the
    ids arriving here are production's. They are not nulled first: the id plus
    a foreign tenant is what identifies a staff member as "was linked in
    production", and nulling it would erase the work list on a crash. Each row
    is re-pointed and stamped as it succeeds.
    """
    report("Syncing payroll employees...")
    staff_members = payroll_employee_sync.staff_needing_seed(tenant_id)
    report(f"  {len(staff_members)} staff need a payroll employee in this organisation")
    if staff_members:
        result = payroll_employee_sync.sync_staff(
            staff_members,
            tenant_id=tenant_id,
            dry_run=dry_run,
            # A demo organisation has never held these people, so most rows will
            # not match and creating them is the whole point of this phase.
            allow_create=True,
        )
        if dry_run:
            report(f"  would link {len(result.linked)} and create {len(result.created)} employees")
        else:
            report(f"  employees: {len(result.linked)} linked, {len(result.created)} created")
            for link in result.linked[:5]:
                report(
                    f"    linked: {link['first_name']} {link['last_name']} "
                    f"-> {link['xero_employee_id']}"
                )
            for created in result.created[:5]:
                report(
                    f"    created: {created['first_name']} {created['last_name']} "
                    f"-> {created['xero_employee_id']}"
                )

    linked_staff = list(
        Staff.objects.filter(xero_tenant_id=tenant_id, xero_user_id__isnull=False).exclude(
            xero_user_id=""
        )
    )
    repaired = 0
    for staff in linked_staff:
        employee_id = str(staff.xero_user_id)
        missing = missing_employee_leave_types(employee_id)
        if not missing:
            continue
        if dry_run:
            report(f"  would assign {', '.join(missing)} to {staff.get_display_full_name()}")
            continue
        ensure_employee_leave_types(employee_id)
        repaired += 1
    if not dry_run:
        report(f"  employee leave eligibility: {repaired} repaired, {len(linked_staff)} ready")


def _documents_phase[TDocument: (Invoice, Quote)](
    kind: _DocumentKind[TDocument],
    tenant_id: str,
    *,
    dry_run: bool,
    report: Callable[[str], None],
) -> None:
    report(f"Syncing {kind.entity}...")
    if dry_run:
        report(f"  would delete {kind.orphans().count()} orphaned {kind.entity}")
        report(f"  would link or create {len(kind.pending(tenant_id))} job-linked {kind.entity}")
        return
    result = seed_documents(kind)
    report(
        f"  {kind.entity}: {result.created} created, {result.linked} linked, "
        f"{result.orphans_deleted} orphans deleted, "
        f"{result.skipped_no_contact} skipped (company not linked)"
    )


def _stock_phase(*, dry_run: bool, report: Callable[[str], None]) -> None:
    report("Syncing stock items...")
    if dry_run:
        report(f"  would sync {stock_pending_sync().count()} stock items")
        return
    result = sync_all_local_stock_to_xero(limit=None)
    report(f"  stock: {result['synced_count']} synced, {result['failed_count']} failed")
    for item in result["failed_items"][:5]:
        report(f"    failed: {item['description']} - {item['reason']}")


def run_seed(entities: set[str], *, dry_run: bool, report: Callable[[str], None]) -> SeedRunOutcome:
    """Run the seed phases against the connected organisation and measure the result.

    The single production guard for every writer below. The per-writer copies
    it replaced were justified by v1's ``--skip-clear``, which reached the
    writes without passing any check; there is now one entry point and no way
    past it, so repeating the assert per writer would be a layered check
    (ADR 0039) that hides which one is authoritative.
    """
    assert_xero_writes_enabled("manage.py seed_xero_from_database")
    # Before any phase and on dry runs too: the refusal is about where this
    # process is pointed, which a run that "only reads" gets wrong just as
    # badly, and reading is how the operator confirms the target.
    assert_not_production_target()
    tenant_id = get_tenant_id()

    cleared = _clear_phase(tenant_id, dry_run=dry_run, report=report)

    if "accounts" in entities:
        _accounts_phase(dry_run=dry_run, report=report)
    if "contacts" in entities:
        _contacts_phase(dry_run=dry_run, report=report)
    # Not an --only phase: jobs and cost lines reference pay items by row, so
    # a mirror whose referenced items are unlinked is broken whatever the
    # operator asked for. Derived from the data, not from "did the clear run":
    # the clear is only the commonest way to get here.
    if pay_items_needing_relink(tenant_id).exists():
        _pay_items_phase(tenant_id, dry_run=dry_run, report=report)
    # Before the financial phases, as in v1: payroll has to exist in the
    # organisation before any transaction is seeded against it, and the
    # employee payload reads the Ordinary Time earnings rate the pay-item
    # re-link above has just re-pointed.
    if "employees" in entities:
        _employees_phase(tenant_id, dry_run=dry_run, report=report)
    if "invoices" in entities:
        _documents_phase(INVOICES, tenant_id, dry_run=dry_run, report=report)
    if "quotes" in entities:
        _documents_phase(QUOTES, tenant_id, dry_run=dry_run, report=report)
    if "stock" in entities:
        _stock_phase(dry_run=dry_run, report=report)

    convergence = seed_convergence(tenant_id)
    # A converged --only run opens the gate, which a phase-counting design
    # refused: the gate states whether the mirror is fully linked, and that is
    # measured from the mirror, not from which options were typed. A dry run
    # never opens it, and a phase that raised never reaches here, so the gate
    # clear_production_xero_ids closed stays closed.
    gate_opened = convergence.converged and not dry_run
    if gate_opened:
        CompanyDefaults.set_xero_sync_enabled(enabled=True)

    return SeedRunOutcome(cleared=cleared, convergence=convergence, gate_opened=gate_opened)
