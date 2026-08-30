"""One-off, cutover phase 0: decrypt v1's credential columns to a file.

Fable: runs while v1 is fully intact, because only v1's own ``.env`` holds
the true key — an explicit ``FIELD_ENCRYPTION_KEY``, else v1's documented
derivation from ``SECRET_KEY`` (v1 settings.py:158-163). Waiting until the
migration to decrypt was rejected: reconfigure renders a fresh v2 ``.env``
that never carries ``FIELD_ENCRYPTION_KEY``, so an explicit key would be
lost and the failure would surface mid-cutover with v1 already stopped.

Reads the five formerly-encrypted columns (phone provider username/password;
supplier credential username/password/api_key) plus the two phone flags from
the v1 database, decrypts, and writes JSON for
``apply_v1_credentials.py`` to load after the data migration. The output
holds live secrets: write it into the root-owned cutover state directory
(mode 600), beside the recorded ``.env`` that already holds SECRET_KEY.

Usage:
  extract_v1_credentials.py --env-file <v1 .env> --db <v1 db name> --output <file.json>
  (connection settings come from the v1 .env's DB_* values; --db overrides the name)

Deletable with scripts/server/cutover/ once both hosts run v2.
"""

import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path

import psycopg
from cryptography.fernet import Fernet, InvalidToken

#: Fernet tokens are version byte 0x80 base64url-encoded — always this prefix.
FERNET_PREFIX = "gAAAA"


def read_env(path: Path) -> dict[str, str]:
    """Minimal KEY=value parse of a .env file (quotes stripped, comments skipped)."""
    values: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def v1_fernet(env: dict[str, str]) -> Fernet:
    """v1's key exactly: explicit FIELD_ENCRYPTION_KEY, else SECRET_KEY derivation."""
    key = env.get("FIELD_ENCRYPTION_KEY", "")
    if not key:
        secret = env.get("SECRET_KEY", "")
        if not secret:
            sys.exit("ERROR: v1 .env has neither FIELD_ENCRYPTION_KEY nor SECRET_KEY.")
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest()).decode(
            "ascii"
        )
    try:
        return Fernet(key)
    except ValueError as exc:
        sys.exit(f"ERROR: v1 FIELD_ENCRYPTION_KEY is not a valid Fernet key: {exc}")


def decrypt_value(fernet: Fernet, value: str | None, where: str) -> str | None:
    """Token values must decrypt; anything else passes through unchanged.

    Fable: a non-token here is already-plaintext v1 data (base_url and
    account_code were never encrypted; a half-migrated row is not this
    script's business) — clearing decisions belong to the apply side.
    """
    if value is None or not value.startswith(FERNET_PREFIX):
        return value
    try:
        return fernet.decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken:
        sys.exit(
            f"ERROR: {where}: Fernet token did not decrypt — wrong key. "
            "Nothing was written; fix the key in the v1 .env reference and re-run."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", required=True, type=Path, help="v1 instance .env")
    parser.add_argument("--db", default="", help="database name (default: v1 .env DB_NAME)")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    env = read_env(args.env_file)
    fernet = v1_fernet(env)
    dbname = args.db or env.get("DB_NAME", "")
    if not dbname:
        sys.exit("ERROR: no database name (pass --db or set DB_NAME in the v1 .env).")

    conninfo = psycopg.conninfo.make_conninfo(
        dbname=dbname,
        user=env.get("DB_USER") or None,
        password=env.get("DB_PASSWORD") or None,
        host=env.get("DB_HOST") or None,
        port=env.get("DB_PORT") or None,
    )
    with psycopg.connect(conninfo) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT downloads_enabled, recording_deletion_enabled, base_url,"
            " username, password, account_code FROM crm_phoneprovidersettings"
        )
        phone_row = cur.fetchone()
        # Keyed by the credential's own pk, which migrates byte-identical — no
        # join to the company table (whose name we would otherwise have to
        # track) and no re-match by name on the apply side.
        cur.execute("SELECT id, label, username, password, api_key FROM quoting_suppliercredential")
        supplier_rows = cur.fetchall()

    phone = None
    if phone_row is not None:
        enabled, deletion, base_url, username, password, account_code = phone_row
        phone = {
            "enabled": bool(enabled),
            "recording_deletion_enabled": bool(deletion),
            "base_url": base_url,
            "username": decrypt_value(fernet, username, "phone username"),
            "password": decrypt_value(fernet, password, "phone password"),
            "account_code": account_code,
        }

    suppliers = [
        {
            "id": str(credential_id),
            "label": label,
            "username": decrypt_value(fernet, username, f"{label} username"),
            "password": decrypt_value(fernet, password, f"{label} password"),
            "api_key": decrypt_value(fernet, api_key, f"{label} api_key"),
        }
        for credential_id, label, username, password, api_key in supplier_rows
    ]

    args.output.write_text(json.dumps({"phone": phone, "suppliers": suppliers}, indent=2))
    args.output.chmod(0o600)
    print(
        f"Extracted: phone={'yes' if phone else 'none'}, "
        f"suppliers={len(suppliers)} -> {args.output}"
    )


if __name__ == "__main__":
    main()
