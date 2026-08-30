"""One-off, cutover phase 0: read curated state out of a live v1 instance.

Fable: runs while v1 is fully intact, because only v1's own ``.env`` holds
the true Fernet key — an explicit ``FIELD_ENCRYPTION_KEY``, else v1's
documented derivation from ``SECRET_KEY`` (v1 settings.py:158-163). Waiting
until the migration was rejected: reconfigure renders a fresh v2 ``.env``
that never carries ``FIELD_ENCRYPTION_KEY``, so an explicit key would be
lost and the failure would surface mid-cutover with v1 already stopped.

Two outputs, both sourced from v1's database, neither auto-generable later:
- ``--output``: the five formerly-encrypted credential columns (phone
  username/password, supplier username/password/api_key) DECRYPTED, plus the
  two phone flags, for ``apply_v1_credentials.py`` to load post-swap. Holds
  live secrets — write it into the root-owned cutover state dir (mode 600).
- ``--company-defaults``: the per-instance ``<instance>.company-defaults.json``
  the cutover requires. It carries the real ``xero_tenant_id``; there is no
  generator otherwise, and it was previously hand-curated. On a cutover the
  file is VALIDATED, not loaded (the real CompanyDefaults arrives with the
  data migration), so this dumps the live v1 singleton and its shop company
  faithfully and forces ``enable_xero_sync`` false to satisfy the gate. Label
  stays ``workflow.companydefaults`` (v1 format); the cutover rewrites it.

Usage:
  extract_v1_credentials.py --env-file <v1 .env> [--db <name>] \\
      [--output creds.json] [--company-defaults <instance>.company-defaults.json]
  (connection settings come from the v1 .env's DB_* values; --db overrides the name)

Deletable with scripts/server/cutover/ once both hosts run v2.
"""

import argparse
import base64
import hashlib
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

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


def _json_safe(value: object) -> object:
    """Serialise the Python types psycopg returns for a Django fixture."""
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"unserialisable fixture value: {type(value)!r}")


def _row_as_dict(cur: psycopg.Cursor, row: tuple[Any, ...]) -> dict[str, Any]:
    if cur.description is None:
        raise RuntimeError("cursor has no column description")
    return {col.name: value for col, value in zip(cur.description, row, strict=True)}


def build_company_defaults(cur: psycopg.Cursor) -> list[dict[str, Any]]:
    """The two-record v1-format fixture: the shop company and the singleton.

    Fable: validated-not-loaded on a cutover, so faithfulness matters only for
    a later fresh rebuild; the real xero_tenant_id is the load-bearing value.
    enable_xero_sync is forced false to satisfy the bootstrap gate, and the
    migrated database carries the real runtime value.
    """
    cur.execute("SELECT * FROM workflow_companydefaults")
    defaults_row = cur.fetchone()
    if defaults_row is None:
        sys.exit("ERROR: v1 has no CompanyDefaults row to build company-defaults.json from.")
    defaults = _row_as_dict(cur, defaults_row)

    shop_company_id = defaults.get("shop_company_id")
    if not shop_company_id:
        sys.exit("ERROR: v1 CompanyDefaults has no shop_company; cannot build the fixture.")
    cur.execute("SELECT * FROM company_company WHERE id = %s", (shop_company_id,))
    company_row = cur.fetchone()
    if company_row is None:
        sys.exit(f"ERROR: v1 shop company {shop_company_id} not found.")
    company = _row_as_dict(cur, company_row)

    defaults_pk = defaults.pop("id")
    defaults["enable_xero_sync"] = False  # bootstrap gate stays closed
    defaults["shop_company"] = defaults.pop("shop_company_id")
    company_pk = _json_safe(company.pop("id"))

    return [
        {"model": "company.company", "pk": company_pk, "fields": company},
        # v1 label; the cutover rewrites it to core.companydefaults.
        {"model": "workflow.companydefaults", "pk": defaults_pk, "fields": defaults},
    ]


def write_credentials(cur: psycopg.Cursor, fernet: Fernet, output: Path) -> None:
    """Decrypt the five credential columns and the phone flags to a file."""
    cur.execute(
        "SELECT downloads_enabled, recording_deletion_enabled, base_url,"
        " username, password, account_code FROM crm_phoneprovidersettings"
    )
    phone_row = cur.fetchone()
    # Keyed by the credential's own pk, which migrates byte-identical — no
    # join to the company table and no re-match by name on the apply side.
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
    output.write_text(json.dumps({"phone": phone, "suppliers": suppliers}, indent=2))
    output.chmod(0o600)
    print(
        f"Credentials: phone={'yes' if phone else 'none'}, suppliers={len(suppliers)} -> {output}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", required=True, type=Path, help="v1 instance .env")
    parser.add_argument("--db", default="", help="database name (default: v1 .env DB_NAME)")
    parser.add_argument("--output", type=Path, help="decrypted credentials JSON")
    parser.add_argument(
        "--company-defaults", type=Path, help="<instance>.company-defaults.json to generate"
    )
    args = parser.parse_args()
    if args.output is None and args.company_defaults is None:
        sys.exit("ERROR: pass --output and/or --company-defaults; nothing to do otherwise.")

    env = read_env(args.env_file)
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
        if args.output is not None:
            write_credentials(cur, v1_fernet(env), args.output)
        if args.company_defaults is not None:
            text = json.dumps(build_company_defaults(cur), indent=2, default=_json_safe)
            if "__" in text:
                sys.exit(
                    "ERROR: generated company-defaults.json contains '__', which the cutover "
                    "validator rejects as an unresolved placeholder. Inspect the v1 data first."
                )
            args.company_defaults.write_text(text)
            args.company_defaults.chmod(0o600)
            print(f"Company defaults -> {args.company_defaults}")


if __name__ == "__main__":
    main()
