# 0048 — A role wipes only what it owns; production wipes need an explicit assertion and are always recoverable

A role may destroy only the databases it owns; postgres ownership and an
explicit CONNECT revoke enforce that. The application layer adds graded
deliberateness — never ceremony — because AI agents legitimately operate in
dev, UAT and production, and safety must stop an overenthusiastic agent
without stopping a deliberate one.

## Rules

**`manage.py reset_public_schema` is the only sanctioned wipe.** It lives in
`apps/diagnostics/management/commands/reset_public_schema.py`, and its refusals
live inside it, so "is this safe" is answerable from the command name. Django's
built-in `flush` is shadowed by a refusal in `apps/core` for the same reason:
it empties every table with no guard and no recovery path.

**Classification is by the configured database name only.** The name is the
one signal an agent cannot usefully spoof, because wiping a database
requires connecting to it; environment variables like `INSTANCE` are never
security inputs. The `dw_<client>_<env>` naming standard
(`scripts/server/common.sh`, env ∈ dev/uat/staging/prod/demo) makes the
suffix deterministic — the same signal
`apps/xero/operator_guards.assert_not_production_target` uses.

| class | rule | policy |
|---|---|---|
| test | starts `test_` or ends `_test` | wipe freely; synthetic data by construction; no snapshot by default |
| app, non-prod | everything else not ending `_prod` | `--database` must name the target; pre-wipe snapshot by default, `--skip-backup` opts out |
| app, prod | ends `_prod` | additionally `--wipe-production`; snapshot mandatory, `--skip-backup` refused |

**Production is wipeable — deliberately, and only recoverably.** PVT and
commissioning need prod wipes. The deliberateness marker is
`--wipe-production`, which appears only in production-purpose runbooks: an
agent copy-pasting a dev/UAT procedure against production fails on the missing
flag. The mandatory snapshot means even a wrong production wipe restores with
one `gunzip -c | psql --single-transaction` line. Recoverability plus one
explicit assertion is the whole mechanism: anything the wiping process can be
made to do, an agent driving that process can also do, so consent files, TTLs
and arming ceremonies add ceremony and no safety.

**Snapshots are taken before anything destructive, or the wipe aborts.**
Single-process `pg_dump -Z6` through the shared scrub-pipeline plumbing
(one exit code — a shell pipe was rejected because gzip exits 0 over a
truncated stream), tmp-then-rename, verified non-empty. Written to the
provisioned instance backup directory when it exists, else
`<checkout>/backups/`; `scripts/cleanup_backups.py` retains `pre_reset_*`
files for 7 days.

**Instances cannot reach each other's data.** `instance.sh` issues
`REVOKE ALL ON DATABASE <main>,<scrub> FROM PUBLIC` plus an explicit owner
`GRANT CONNECT` in its idempotent configure SQL, closing PUBLIC's implicit
CONNECT under the cluster's `local all all scram-sha-256` pg_hba. One
`reconfigure` retrofits a pre-existing instance. The `postgres` maintenance
database is deliberately untouched — Django's test runner connects to it to
create and drop test databases. The REVOKE does not stop a determined actor
holding the owner role's own password; nightly and predeploy backups bound
that damage.

**A destructive predicate is proven against real data before it runs.** A
`WHERE` clause written from the model's contract deletes what the contract
says is junk, and production data is the only witness to what the contract got
wrong (ADR 0015): run the predicate as a read against a restore, review the
rows it selects, then run it. ADR 0015's dry-run rule covers migrations; this
covers every ad-hoc delete, in a shell or a command.

**Test databases isolate per checkout automatically.** Dev checkouts derive
the test database name from a hash of the checkout path
(`config/settings_test.py`), so concurrent worktrees never collide and
`--reuse-db` keeps working; instances use their per-tenant CREATEDB test
role. The suite refuses to boot against a `_prod` database unless that
per-tenant role is configured. Each session exporting its own `DB_NAME` was
rejected because it relied on memory.

## Do not

- **A raw `DROP SCHEMA` or `dbshell -c` line in a runbook or script** — to a
  reviewer and to a permission layer it is indistinguishable from an agent
  mistake; the command name is what makes the wipe recognisable.
