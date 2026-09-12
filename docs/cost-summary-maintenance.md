# Cost summary maintenance

`CostSet.summary` caches the cost, revenue and time hours derived from its cost
lines. Cost lines remain the source of truth. Normal saves and deletes apply the
persisted before/after contributions using exact decimal arithmetic, in the same
transaction and under the same ordered job locks as the ledger change. Transfers
update both owners. Extra summary keys, including archived quote revisions, are
preserved.

## Check and repair

Run in the instance's configured environment:

```bash
uv run python manage.py reconcile_cost_summaries --job 96881
uv run python manage.py reconcile_cost_summaries --all
uv run python manage.py reconcile_cost_summaries --job 96881 --repair
uv run python manage.py reconcile_cost_summaries --all --repair
```

Without `--repair`, the command only reads and exits unsuccessfully if any cache
is incorrect. Repair locks and rechecks each job independently, replacing only
incorrect live totals. It never edits cost lines, stock movements or archived
quote revisions. Changed jobs receive a fresh version and request the existing
PDF refresh after commit. Correct caches are left alone. A stopped repair can be
restarted: completed jobs stay committed and already-correct totals are no-ops.

Application maintenance code calls `CostSet.recalculate_summary()` inside its
transaction after bulk cost-line changes. It returns whether totals changed;
`summary_is_current()` provides the read-only comparison. Normal model writes do
not scan historical lines. Quote copying, revision clearing and the operator time
transfer script explicitly rebuild after their bulk operations.

Direct SQL, `QuerySet.update()`, bulk creation and bulk deletion bypass normal
model maintenance. For direct database maintenance, stop application and worker
writers, retain the affected job numbers, make the reviewed ledger changes, then
repair and check those jobs before writers resume. Rebuilding a cache cannot
repair an incorrect ledger or supply missing inventory movement evidence.

## First deployment

Rehearse the complete migration chain against a current scrubbed production
snapshot, including the inventory repair dispositions required by this branch.
Stop application, worker and scheduled writers during rollout. Job migration
`0011_incremental_cost_summary` locks the costing tables, rebuilds every incorrect
cache from its cost lines, preserves object extension keys and archived revisions,
and enforces three numeric live totals. Empty cost sets get zero totals. The
migration changes job freshness for repaired caches but never changes ledger rows.

After migration, run `reconcile_cost_summaries --all` and require a clean result.
Resume the new application and workers, then request the existing PDF refresh
reconciler once so jobs changed by the data migration are discovered:

```bash
uv run python manage.py shell -c 'from apps.job.tasks import request_job_summary_pdf_refresh; request_job_summary_pdf_refresh()'
```

Do not mix old full-rebuild writers with the new incremental writers during the
rollout. Reversing the schema migration does not restore previously wrong caches.
