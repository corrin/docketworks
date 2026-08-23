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

import wave
from io import BytesIO

#: Marks the companies, jobs, people and phone calls a run creates.
TEST_DATA_PREFIX = "[TEST]"
#: Prefixes older specs used; the residue they left is still recognised.
LEGACY_E2E_PREFIXES = ("E2E Test Client", "E2E Modal Client", "E2E Test Supplier")
E2E_NAME_PREFIXES = (TEST_DATA_PREFIX, *LEGACY_E2E_PREFIXES)
#: The standing fixture company that UI-seeded specs work against. Seed data,
#: never residue: it is preserved by the cleanup and must never be archived.
TEST_COMPANY_NAME = "ABC Carpet Cleaning TEST IGNORE"


def is_e2e_name(name: str) -> bool:
    """Whether a row's human-readable text marks it as E2E-created residue.

    Usually a company, job or person name. A phone call has no name, so the
    text is its description — the same prefix, checked the same way, because
    a second convention for one model is a second thing to remember.
    """
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


def silent_wav(seconds: float) -> bytes:
    """``seconds`` of silence as a real WAV (1ch, 16-bit, 8 kHz).

    The one fabricated recording: the E2E seed stores it and the unit tests
    feed it to the archive, which measures every file it stores and refuses
    bytes that are not audio. Generated rather than committed — a binary
    fixture would be a second thing to keep.
    """
    buffer = BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * round(8000 * seconds))
    return buffer.getvalue()
