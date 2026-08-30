"""The v1 credential decryptor: key derivation, round trip, wrong-key refusal.

Pure-function coverage of extract_v1_credentials — no database. The apply
side is a thin Django writer exercised by the cutover rehearsal; what earns
a unit test here is the crypto, where a wrong answer means either a failed
cutover or ciphertext written as a live password.
"""

import base64
import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

_MODULE_PATH = Path(__file__).resolve().parents[1] / "ops" / "extract_v1_credentials.py"
_spec = importlib.util.spec_from_file_location("extract_v1_credentials", _MODULE_PATH)
assert _spec and _spec.loader
extract = importlib.util.module_from_spec(_spec)
sys.modules["extract_v1_credentials"] = extract
_spec.loader.exec_module(extract)


def _derived_key(secret: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest()).decode("ascii")


def test_derives_the_key_from_secret_key_when_field_key_absent() -> None:
    """v1 settings.py:158-163 — the SHA-256 derivation must match byte for byte,
    or every token on a host without an explicit FIELD_ENCRYPTION_KEY fails."""
    secret = "a-production-secret-key-value"
    fernet = extract.v1_fernet({"SECRET_KEY": secret})
    token = Fernet(_derived_key(secret)).encrypt(b"2talk-password").decode()
    assert fernet.decrypt(token.encode()).decode() == "2talk-password"


def test_explicit_field_key_wins_over_derivation() -> None:
    explicit = Fernet.generate_key().decode()
    fernet = extract.v1_fernet({"FIELD_ENCRYPTION_KEY": explicit, "SECRET_KEY": "ignored"})
    token = Fernet(explicit.encode()).encrypt(b"secret").decode()
    assert fernet.decrypt(token.encode()).decode() == "secret"


def test_token_round_trips_and_plaintext_passes_through() -> None:
    fernet = extract.v1_fernet({"SECRET_KEY": "s"})
    token = Fernet(_derived_key("s")).encrypt(b"hunter2").decode()
    assert extract.decrypt_value(fernet, token, "where") == "hunter2"
    # base_url/account_code were never encrypted; a non-token is v1 plaintext.
    assert extract.decrypt_value(fernet, "https://portal.2talk.co.nz", "where") == (
        "https://portal.2talk.co.nz"
    )
    assert extract.decrypt_value(fernet, None, "where") is None


def test_wrong_key_exits_without_writing() -> None:
    """A token that will not decrypt is a hard stop — never a silent clear of
    a real credential (the failure mode the whole pair exists to prevent)."""
    token = Fernet(_derived_key("the-real-secret")).encrypt(b"pw").decode()
    wrong = extract.v1_fernet({"SECRET_KEY": "a-different-secret"})
    with pytest.raises(SystemExit) as exc:
        extract.decrypt_value(wrong, token, "phone password")
    assert "did not decrypt" in str(exc.value)


def test_missing_both_keys_is_a_hard_error() -> None:
    with pytest.raises(SystemExit) as exc:
        extract.v1_fernet({})
    assert "neither" in str(exc.value).lower()


def test_env_parse_strips_quotes_and_comments(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text('# comment\nSECRET_KEY="quoted value"\nDB_NAME=plain\n\nDB_USER=\n')
    parsed = extract.read_env(env_file)
    assert parsed["SECRET_KEY"] == "quoted value"
    assert parsed["DB_NAME"] == "plain"
    assert parsed["DB_USER"] == ""


class _FakeCursor:
    """Minimal psycopg-cursor stand-in: scripted (description, rows) per execute."""

    def __init__(self, script: dict[str, tuple[list[str], list[tuple[object, ...]]]]) -> None:
        self._script = script
        self.description: list[object] | None = None
        self._rows: list[tuple[object, ...]] = []

    def execute(self, sql: str, _params: tuple[object, ...] = ()) -> None:
        for key, (cols, rows) in self._script.items():
            if key in sql:
                self.description = [type("Col", (), {"name": c}) for c in cols]
                self._rows = list(rows)
                return
        raise AssertionError(f"unscripted SQL: {sql}")

    def fetchone(self) -> tuple[object, ...] | None:
        return self._rows[0] if self._rows else None


def test_company_defaults_is_a_valid_two_record_fixture() -> None:
    import uuid

    shop_id = uuid.uuid4()
    cur = _FakeCursor(
        {
            "workflow_companydefaults": (
                ["id", "company_name", "xero_tenant_id", "enable_xero_sync", "shop_company_id"],
                [(1, "MSM", str(uuid.uuid4()), True, shop_id)],
            ),
            "company_company": (
                ["id", "name"],
                [(shop_id, "MSM Shop")],
            ),
        }
    )
    records = extract.build_company_defaults(cur)

    assert [r["model"] for r in records] == ["company.company", "workflow.companydefaults"]
    defaults = next(r for r in records if r["model"] == "workflow.companydefaults")["fields"]
    # The gate the validator enforces:
    assert defaults["enable_xero_sync"] is False  # forced closed, though v1 had it True
    __import__("uuid").UUID(defaults["xero_tenant_id"])  # a real, parseable tenant id
    assert "shop_company" in defaults and "shop_company_id" not in defaults
    assert "id" not in defaults  # promoted to pk


# --- apply-side cross-check (imported the same way, no Django needed) ---
_APPLY_PATH = Path(__file__).resolve().parents[1] / "ops" / "apply_v1_credentials.py"
_apply_spec = importlib.util.spec_from_file_location("apply_v1_credentials", _APPLY_PATH)
assert _apply_spec and _apply_spec.loader
apply = importlib.util.module_from_spec(_apply_spec)
sys.modules["apply_v1_credentials"] = apply
_apply_spec.loader.exec_module(apply)


class _Cred:
    def __init__(self, label: str) -> None:
        self.label = label


def test_cross_check_resolves_matching_rows() -> None:
    rows = {"a": _Cred("Steel & Tube"), "b": _Cred("BHP")}
    suppliers = [
        {"id": "a", "label": "Steel & Tube"},
        {"id": "b", "label": "BHP"},
    ]
    resolved, problems = apply.cross_check_suppliers(suppliers, rows.get)
    assert problems == []
    assert [entry["id"] for _, entry in resolved] == ["a", "b"]


def test_cross_check_flags_a_label_mismatch_and_a_missing_row() -> None:
    rows = {"a": _Cred("Renamed Supplier")}
    suppliers = [
        {"id": "a", "label": "Steel & Tube"},  # pk hit, label differs
        {"id": "gone", "label": "BHP"},  # pk miss
    ]
    resolved, problems = apply.cross_check_suppliers(suppliers, rows.get)
    assert resolved == []
    assert len(problems) == 2
    assert any("label mismatch" in p for p in problems)
    assert any("not in the migrated database" in p for p in problems)
