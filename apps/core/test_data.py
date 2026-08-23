"""The names E2E specs give the rows they create.

Fable: one home rather than a copy per reader. Three independent apps read
these — diagnostics (the local cleanup), xero (archiving the contacts those
rows became, and ignoring a finished run's Xero objects) and their tests —
and the import-linter contract forbids diagnostics and xero importing each
other, so the copies each carried could only drift. core is the one layer
every app may import. ``frontend/tests/scripts/db-backup-utils.ts`` and
``frontend/tests/e2e/helpers.ts`` carry the same names in TypeScript; no
import is possible across that boundary.
"""

#: Marks the companies, jobs and people a run creates.
TEST_DATA_PREFIX = "[TEST]"
#: Prefixes older specs used; the residue they left is still recognised.
LEGACY_E2E_PREFIXES = ("E2E Test Client", "E2E Modal Client", "E2E Test Supplier")
E2E_NAME_PREFIXES = (TEST_DATA_PREFIX, *LEGACY_E2E_PREFIXES)
#: The standing fixture company that UI-seeded specs work against. Seed data,
#: never residue: it is preserved by the cleanup and must never be archived.
TEST_COMPANY_NAME = "ABC Carpet Cleaning TEST IGNORE"


def is_e2e_name(name: str) -> bool:
    """Whether a company, job or person name marks it as E2E-created residue."""
    return name.startswith(E2E_NAME_PREFIXES)


def is_test_company_name(name: str | None) -> bool:
    """Whether a company name belongs to the E2E world: residue or the standing company.

    Fable: broader than ``is_e2e_name`` on purpose. The inbound Xero filter
    asks "is this one of ours?" and must include the standing company, whose
    invoices and quotes a run raises; the archiver asks "is this residue?" and
    must exclude it. Two predicates, one fact each.
    """
    if not name:
        return False
    return is_e2e_name(name) or name == TEST_COMPANY_NAME
