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
