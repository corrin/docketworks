# 0048 — Own-what-you-wipe database safety

A role may destroy only the databases it owns; postgres ownership and an
explicit CONNECT revoke enforce that. The application layer adds graded
deliberateness — never ceremony — because AI agents legitimately operate in
dev, UAT and production, and safety must stop an overenthusiastic agent
without stopping a deliberate one.

## Rules

**`manage.py reset_public_schema` is the only sanctioned wipe.** No runbook
or script carries a raw `DROP SCHEMA` / `dbshell -c` line for the default
database: a raw destructive SQL line is indistinguishable — to a reviewer
and to a permission layer — from an agent mistake, which is exactly how the
2026-08-15 restore run stalled. The command's refusals live inside it, so
"is this safe" is answerable from the command name. Django's built-in
`flush` is shadowed by a refusal in `apps/core` for the same reason: it
empties every table with no guard and no recovery path.

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
commissioning need prod wipes, so a flat refusal was rejected. The
deliberateness marker is `--wipe-production`, which appears only in
production-purpose runbooks: an agent copy-pasting a dev/UAT procedure
against production fails on the missing flag. The mandatory snapshot means
even a wrong production wipe restores with one `gunzip -c | psql
--single-transaction` line.

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
`reconfigure` retrofits a pre-existing instance (cutover-checklist item).
The `postgres` maintenance database is deliberately untouched — Django's
test runner connects to it to create and drop test databases.

**Test databases isolate per checkout automatically.** Dev checkouts derive
the test database name from a hash of the checkout path
(`config/settings_test.py`), so concurrent worktrees never collide and
`--reuse-db` keeps working; instances use their per-tenant CREATEDB test
role. The suite refuses to boot against a `_prod` database unless that
per-tenant role is configured. The rejected alternative — each session
remembering to export its own `DB_NAME` — failed every time it relied on
memory.

## Rejected alternatives

Consent files, TTLs and arming ceremonies were rejected as overengineering:
anything the wiping process can be made to do, an agent driving that
process can also do, and anything root-gated is already covered by root
being root — the out-of-band path by design. The graded mechanism is
instead recoverability (snapshots) plus one explicit assertion whose only
documented home is the runbook that means it.

## Honest limits

The ladder stops mistakes and overenthusiasm; the REVOKE stops
cross-instance access; neither stops a determined actor holding the owner
role's own password — raw psql schema-drops by the owner cannot be
technically closed. Nightly and predeploy backups bound that damage.
Residual accepted risks: transient test databases carry default ACLs
(synthetic data only), and a CREATEDB test role can name-squat or burn disk
(detectable, quota-bounded).
