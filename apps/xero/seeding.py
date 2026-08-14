"""Push a restored database into a non-production Xero org.

After a scrubbed production dump is restored into a dev/UAT instance, every
mirror id in the database (``Company.xero_contact_id``, ``Invoice.xero_id``,
the chart of accounts, ...) points at entities in the PRODUCTION Xero org that
do not exist in the connected demo org. Left alone, the first sync does not
recognise the local rows and creates duplicate companies, invoices and quotes.

This module re-points the mirror: clear the production ids, then link local
records to their demo-org counterparts where those exist and create them where
they do not. It is operator-run tooling (``manage.py seed_xero_from_database``)
and is deliberately loud — a partial seed that looks successful is worse than a
failed one, because the duplicates only appear on the next sync.

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
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.conf import settings
from xero_python.accounting import AccountingApi, LineItem
from xero_python.accounting import Contact as XeroContact
from xero_python.accounting import Invoice as XeroInvoice
from xero_python.accounting import Quote as XeroQuote

from apps.accounting.models import Invoice, Quote
from apps.company.models import Company
from apps.job.models import Job
from apps.purchasing.models import PurchaseOrder, Stock
from apps.xero.auth import get_api_client, get_tenant_id
from apps.xero.contacts import contact_from_company
from apps.xero.helpers import clean_payload, convert_to_pascal_case, sanitize_for_xero
from apps.xero.models import XeroAccount, XeroPayItem, XeroSyncCursor
from apps.xero.transforms import process_xero_data

logger = logging.getLogger(__name__)

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


# --- Production guards ------------------------------------------------------


def assert_not_production_target() -> None:
    """Refuse to run against a production database or the production Xero org.

    Two independent checks because either one alone has a hole: the database
    name is checked before any credential is needed, and the tenant check
    catches a non-prod database that has been pointed at the live Xero org
    (which is how a seed would write fabricated ids into real accounts).
    """
    db_name = str(settings.DATABASES["default"]["NAME"])
    # The `dw_<company>_<env>` naming standard validates env against
    # {dev,uat,staging,prod}, so the `_prod` suffix is a deterministic
    # instance-scoped signal — it works on multi-instance servers where
    # /etc/machine-id is shared.
    if db_name.endswith("_prod"):
        raise ValueError(
            f"Refusing to seed Xero against production database: {db_name}. "
            "This operation is only for development environments after a production restore."
        )

    tenant_id = get_tenant_id()
    if tenant_id == settings.PRODUCTION_XERO_TENANT_ID:
        raise ValueError(
            f"Refusing to seed Xero against the production Xero tenant ({tenant_id}). "
            "Connect the instance to its own demo/UAT organisation first."
        )


# --- Contacts ---------------------------------------------------------------


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
            company.save(update_fields=["xero_contact_id"])
            total_created += 1
            logger.info(
                "Created Xero contact for company %s: %s", company.name, company.xero_contact_id
            )

    return total_created


def seed_companies_to_xero(companies: Iterable[Company]) -> SeedContactsResult:
    """Link companies to existing Xero contacts by name; create the remainder."""
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
        company.save(update_fields=["xero_contact_id"])
        logger.info(
            "Linked company %s to existing Xero contact %s", company.name, existing_contact_id
        )

    created = bulk_create_contacts_in_xero(companies_to_create)
    return SeedContactsResult(linked=len(companies_to_link), created=created)


# --- Idempotence lookups ----------------------------------------------------


def fetch_xero_entity_lookup(
    entity_name: str,
    key_func: Callable[[Any], str | None],
    value_func: Callable[[Any], str],
) -> dict[str, str]:
    """Fetch every entity of a type from Xero as ``{key: value}``.

    Reuses ENTITY_CONFIGS for API-method resolution, pagination mode and
    params so the seed reads Xero exactly the way the sync engine does. The
    ``Any`` in the callbacks is the SDK seam: ENTITY_CONFIGS keys a different
    untyped SDK model per entity, and each call site immediately narrows to
    the two fields it reads.
    """
    # Call-time import: sync imports transforms, which imports models; the
    # command that calls this must not drag that in at module scope.
    from apps.xero.sync import ENTITY_CONFIGS, _resolve_api_method  # noqa: PLC0415

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

        for item in items:
            key = key_func(item)
            if key:
                lookup[key] = value_func(item)

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

    accounting_api = AccountingApi(get_api_client())
    response = accounting_api.get_accounts(get_tenant_id())
    xero_accounts = response.accounts or []
    logger.info("Fetched %d accounts from the target Xero org", len(xero_accounts))

    updated = 0
    created = 0
    for account in xero_accounts:
        if account.account_id is None or account.name is None:
            raise ValueError(f"Xero account payload missing id or name (id={account.account_id!r})")
        _row, was_created = XeroAccount.objects.update_or_create(
            account_name=account.name,
            defaults={
                "xero_id": account.account_id,
                "account_code": account.code or None,
                "description": account.description or None,
                # .value, not str(): the SDK deserialises type as an
                # AccountType enum, and str() persists "AccountType.BANK".
                "account_type": account.type.value if account.type else None,
                "tax_type": account.tax_type or None,
                "enable_payments": bool(account.enable_payments_to_account),
                "xero_last_modified": account._updated_date_utc,
                # Never-synced: the row now describes the target org and the
                # next sync must pull it down rather than skip it.
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


def _sales_account_code() -> str | None:
    """Return the account code every seeded invoice and quote line is coded to."""
    return XeroAccount.objects.get(account_name=SALES_ACCOUNT_NAME).account_code


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


def _build_invoice_payload(invoice: Invoice, account_code: str | None) -> dict[str, Any]:
    """Build the Xero create payload for one restored invoice."""
    if invoice.job is None:
        raise ValueError(f"Invoice {invoice.number} has no job and must not be seeded")

    line_items = []
    for line in invoice.line_items.all():
        quantity = line.quantity if line.quantity is not None else Decimal("1")
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
                tax_amount=float(line.tax_amount) if line.tax_amount else None,
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


def _build_quote_payload(quote: Quote, account_code: str | None) -> dict[str, Any]:
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


def seed_invoices() -> SeedDocumentsResult:
    """Delete orphaned invoices, then link or re-create job-linked ones."""
    orphans_deleted, _ = Invoice.objects.filter(job__isnull=True).delete()
    if orphans_deleted:
        logger.info("Deleted %d orphaned invoices (no job link)", orphans_deleted)

    tenant_id = get_tenant_id()
    job_invoices = list(
        Invoice.objects.filter(job__isnull=False)
        .exclude(xero_tenant_id=tenant_id)
        .select_related("job", "company")
    )
    if not job_invoices:
        return SeedDocumentsResult(
            created=0, linked=0, orphans_deleted=orphans_deleted, skipped_no_contact=0
        )

    to_seed = [inv for inv in job_invoices if inv.company.xero_contact_id]
    skipped_no_contact = len(job_invoices) - len(to_seed)
    if skipped_no_contact:
        logger.warning(
            "Skipping %d invoices whose company has no xero_contact_id - run contacts first",
            skipped_no_contact,
        )
    if not to_seed:
        return SeedDocumentsResult(
            created=0,
            linked=0,
            orphans_deleted=orphans_deleted,
            skipped_no_contact=skipped_no_contact,
        )

    numbered = _numbered_documents(to_seed)

    existing = fetch_xero_entity_lookup(
        "invoices", lambda inv: inv.invoice_number, lambda inv: inv.invoice_id
    )
    logger.info("Found %d existing invoices in the target Xero org", len(existing))

    linked = 0
    to_create: list[tuple[str, Invoice]] = []
    for number, invoice in numbered:
        existing_id = existing.get(number)
        if not existing_id:
            to_create.append((number, invoice))
            continue
        invoice.xero_id = existing_id
        invoice.xero_tenant_id = tenant_id
        # Nulled so the next sync pulls the target org's authoritative record.
        invoice.xero_last_synced = None
        invoice.save(update_fields=["xero_id", "xero_tenant_id", "xero_last_synced"])
        linked += 1
        logger.info("Linked existing invoice %s (%s)", invoice.number, invoice.company.name)

    created = _batch_create_invoices(to_create, tenant_id)
    return SeedDocumentsResult(
        created=created,
        linked=linked,
        orphans_deleted=orphans_deleted,
        skipped_no_contact=skipped_no_contact,
    )


def _batch_create_invoices(invoices: list[tuple[str, Invoice]], tenant_id: str) -> int:
    """Create invoices in Xero in batches; map the response back by number."""
    if not invoices:
        return 0

    accounting_api = AccountingApi(get_api_client())
    account_code = _sales_account_code()
    by_number = dict(invoices)
    created = 0

    for start in range(0, len(invoices), BATCH_SIZE):
        batch = invoices[start : start + BATCH_SIZE]
        batch_number = start // BATCH_SIZE + 1
        payloads = [_build_invoice_payload(invoice, account_code) for _number, invoice in batch]

        logger.info("Sending batch %d of %d invoices", batch_number, len(payloads))
        response = accounting_api.create_invoices(tenant_id, invoices={"Invoices": payloads})
        if not response.invoices:
            raise ValueError(f"Empty response from Xero for invoice batch {batch_number}")

        for created_invoice in response.invoices:
            # A response with no number at all is the same failure as an
            # unrecognised one: nothing to map it back to.
            local = by_number.get(created_invoice.invoice_number or "")
            if local is None:
                # Not a warning: the local invoice stays unlinked, and the next
                # sync then creates a duplicate — the corruption this command
                # exists to prevent.
                raise ValueError(
                    f"Xero invoice {created_invoice.invoice_number!r} could not be mapped "
                    f"back to a local record. Xero renumbered a submitted invoice; the "
                    f"remaining local invoices in this batch are unlinked."
                )
            if not created_invoice.invoice_id:
                raise ValueError(f"Xero response missing invoice_id for {local.number}")
            local.xero_id = created_invoice.invoice_id
            local.xero_tenant_id = tenant_id
            local.xero_last_synced = None
            local.save(update_fields=["xero_id", "xero_tenant_id", "xero_last_synced"])
            created += 1
            logger.info("Seeded invoice %s (%s)", local.number, local.company.name)

    return created


def seed_quotes() -> SeedDocumentsResult:
    """Delete orphaned quotes, then link or re-create job-linked ones."""
    orphans_deleted, _ = Quote.objects.filter(job__isnull=True).delete()
    if orphans_deleted:
        logger.info("Deleted %d orphaned quotes (no job link)", orphans_deleted)

    tenant_id = get_tenant_id()
    job_quotes = list(
        Quote.objects.filter(job__isnull=False)
        .exclude(xero_tenant_id=tenant_id)
        .select_related("job", "company")
    )
    if not job_quotes:
        return SeedDocumentsResult(
            created=0, linked=0, orphans_deleted=orphans_deleted, skipped_no_contact=0
        )

    to_seed = [quote for quote in job_quotes if quote.company.xero_contact_id]
    skipped_no_contact = len(job_quotes) - len(to_seed)
    if skipped_no_contact:
        logger.warning(
            "Skipping %d quotes whose company has no xero_contact_id - run contacts first",
            skipped_no_contact,
        )
    if not to_seed:
        return SeedDocumentsResult(
            created=0,
            linked=0,
            orphans_deleted=orphans_deleted,
            skipped_no_contact=skipped_no_contact,
        )

    numbered = _numbered_documents(to_seed)

    existing = fetch_xero_entity_lookup(
        "quotes", lambda quote: quote.quote_number, lambda quote: quote.quote_id
    )
    logger.info("Found %d existing quotes in the target Xero org", len(existing))

    linked = 0
    to_create: list[tuple[str, Quote]] = []
    for number, quote in numbered:
        existing_id = existing.get(number)
        if not existing_id:
            to_create.append((number, quote))
            continue
        quote.xero_id = existing_id
        quote.xero_tenant_id = tenant_id
        quote.save(update_fields=["xero_id", "xero_tenant_id"])
        linked += 1
        logger.info("Linked existing quote %s (%s)", quote.number, quote.company.name)

    created = _batch_create_quotes(to_create, tenant_id)
    return SeedDocumentsResult(
        created=created,
        linked=linked,
        orphans_deleted=orphans_deleted,
        skipped_no_contact=skipped_no_contact,
    )


def _batch_create_quotes(quotes: list[tuple[str, Quote]], tenant_id: str) -> int:
    """Create quotes in Xero in batches; map the response back by number."""
    if not quotes:
        return 0

    accounting_api = AccountingApi(get_api_client())
    account_code = _sales_account_code()
    by_number = dict(quotes)
    created = 0

    for start in range(0, len(quotes), BATCH_SIZE):
        batch = quotes[start : start + BATCH_SIZE]
        batch_number = start // BATCH_SIZE + 1
        payloads = [_build_quote_payload(quote, account_code) for _number, quote in batch]

        logger.info("Sending batch %d of %d quotes", batch_number, len(payloads))
        response = accounting_api.create_quotes(tenant_id, quotes={"Quotes": payloads})
        if not response.quotes:
            raise ValueError(f"Empty response from Xero for quote batch {batch_number}")

        for created_quote in response.quotes:
            # As for invoices: a missing number is an unmappable response.
            local = by_number.get(created_quote.quote_number or "")
            if local is None:
                raise ValueError(
                    f"Xero quote {created_quote.quote_number!r} could not be mapped back "
                    f"to a local record. Xero renumbered a submitted quote; the remaining "
                    f"local quotes in this batch are unlinked."
                )
            if not created_quote.quote_id:
                raise ValueError(f"Xero response missing quote_id for {local.number}")
            local.xero_id = created_quote.quote_id
            local.xero_tenant_id = tenant_id
            local.save(update_fields=["xero_id", "xero_tenant_id"])
            created += 1
            logger.info("Seeded quote %s (%s)", local.number, local.company.name)

    return created


# --- Phase 0: clear the production ids --------------------------------------


def clear_production_xero_ids() -> ClearedIdsResult:
    """Null every mirror id that points at the production Xero org.

    ORM rather than v1's raw SQL with information_schema probes: those existed
    because v1's schema was still churning, and a missing column is now a
    migration defect that must fail loudly rather than be skipped.

    Invoice and Quote ``xero_id`` are NOT NULL and cannot be cleared here;
    ``seed_invoices``/``seed_quotes`` handle them by deleting orphans and
    re-creating job-linked documents in the target org.
    """
    assert_not_production_target()

    cleared = {
        "company.xero_contact_id": Company.objects.filter(xero_contact_id__isnull=False).update(
            xero_contact_id=None
        ),
        "job.xero_project_id": Job.objects.filter(xero_project_id__isnull=False).update(
            xero_project_id=None
        ),
        "purchaseorder.xero_id": PurchaseOrder.objects.filter(xero_id__isnull=False).update(
            xero_id=None
        ),
        "stock.xero_id": Stock.objects.filter(xero_id__isnull=False).update(xero_id=None),
        "xeropayitem.xero_id": XeroPayItem.objects.filter(xero_id__isnull=False).update(
            xero_id=None, xero_tenant_id=None
        ),
        # v1 left the cursors in place. They are high-water marks against the
        # PRODUCTION org, so the first sync against the demo org skips every
        # record older than them. Deleting is safe: the fallback is the same
        # max(xero_last_modified) high-water mark the cursors cache.
        "xerosynccursor (deleted)": XeroSyncCursor.objects.all().delete()[0],
    }

    # Staff.xero_user_id is deliberately preserved: it records which staff were
    # linked in production and is the crash-recovery marker the (Phase 4)
    # employee phase reads to know what to re-link.
    logger.info("Cleared production Xero ids: %s", cleared)
    return ClearedIdsResult(cleared=cleared)
