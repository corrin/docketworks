# 0053 — Integration credentials are typed columns on one singleton

Every credential the install uses to reach an external service lives in the database, on
`apps.core.models.IntegrationSettings`, as a typed column of its own. Nothing reads a vendor
credential from the environment; `.env` holds what Django needs to boot (database, Redis,
signing keys, paths) and nothing the application could change without a deploy.

## Rules

- **One column per credential, on one row.** `IntegrationSettings` is a singleton (`id=1`)
  holding everything the install has exactly one of: the Google Maps key, the phone provider's
  connection, and later the Drive service account and SMTP. A new integration adds columns and
  a migration. Columns rather than rows because every read is then a typed attribute mypy can
  see (ADR 0028), each column carries its own not-blank constraint (ADR 0040), and the set of
  integrations is in code — an unconfigured one is `None` at a known attribute, never a missing
  row discovered at runtime. A row-per-integration table can only be generic columns plus a
  JSON bag, which is the shape the read-side fallback backlog exists to remove.
- **N-of integrations keep their own typed tables.** `XeroApp` (a rotation pair with token
  state), `AIProvider` (a list with a default) and `SupplierCredential` (one per supplier) are
  many of the same kind, so each is its own table where every row is the same shape. The
  boundary is cardinality, never vendor: a second Google credential is another column, not a
  second Google table.
- **Never `CompanyDefaults`.** Its GET is any-staff boot data whose response is derived from
  every column, so a credential there is handed to every user on every page load. It holds
  business configuration; `IntegrationSettings` holds how the install reaches the outside.
- **Reads never write.** `get_solo()` returns the row or raises `ImproperlyConfigured`; the
  row is created by `core/0003_integration_settings_row`, which the cutover script re-applies
  after the restore. A `get_or_create` on a read path makes a GET a mutation.
- **Secrets are write-only on the wire.** The one admin surface is superuser-only
  `GET`/`PATCH /api/integration-settings/` and the `/admin/integrations` page. The response
  carries `has_<column>` booleans in place of secret values; the request takes a value to set
  or `null` to clear, and an omitted field leaves the stored value alone.
- **One seed, one check, one scrub.** `scripts/server/instance.sh` renders every column from
  the root-owned credentials file into `integration-settings.json`, and
  `manage.py load_integration_settings` applies each integration only while that
  integration's columns are all unset — a restored instance keeps the phone login its admin
  entered and still receives the Maps key. The command also creates the row a scrubbed
  restore leaves missing.
  `scripts/ops/restore_checks/check_integration_settings.py` proves each credential the way the
  app uses it (a live Address Validation call for the Maps key). The scrubber truncates the
  table whole, and its private-table list is the scrub contract for every column at once.
- **The table is named for its history until the post-cutover rename.** `db_table` is
  `crm_phoneprovidersettings`, the table v1 created for the phone row: the v1 dump restores by
  table name and the scrubber lists it, so adopting it moves no data and changes no contract.
  The physical rename belongs to the purge of v1/v2 names in `docs/rewrite-status.md`.

## Do not

- **Do not add a vendor credential to `.env`, `.env.example` or a server template.** The
  credentials file feeds the database; the environment is not a second home.
- **Do not echo a secret back in any response**, including "for the edit form" — the form
  shows configured/not configured and takes a new value.
- **Do not add a generic `extra_config` JSON column** to absorb a new integration's fields. The
  migration is the point.
