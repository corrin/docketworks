"""The names E2E specs give the rows they create.

Here rather than in the cleanup command because two independent top-layer
apps read them: diagnostics (the local cleanup) and xero (archiving the
contacts those rows became). ``frontend/tests/scripts/db-backup-utils.ts``
carries the same prefix for the preflight; a different language, so no import.
"""

TEST_DATA_PREFIX = "[TEST]"
LEGACY_E2E_PREFIXES = ("E2E Test Client", "E2E Modal Client", "E2E Test Supplier")
E2E_NAME_PREFIXES = (TEST_DATA_PREFIX, *LEGACY_E2E_PREFIXES)


def is_e2e_name(name: str) -> bool:
    """Whether a company, job or person name marks it as E2E-created."""
    return name.startswith(E2E_NAME_PREFIXES)
