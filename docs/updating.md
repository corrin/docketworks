# Updating the Application

This guide covers updating an existing installation to the latest version.

## Development Environment

If you're running the application locally for development:

1. Pull the latest code:

   ```bash
   git pull
   ```

2. Update dependencies:

   ```bash
   poetry install
   ```

3. Apply any database changes:

   ```bash
   python manage.py migrate
   ```

4. Restart the development server if running

## Server Environment (Multi-Tenant)

**This section is the deploy runbook.** PR merged to `main`? SSH into the server and run:

```bash
# One client
sudo ./scripts/server/deploy.sh <client>-<env>

# Or all instances
sudo ./scripts/server/deploy.sh --all
```

That's it for a normal code release. `deploy.sh` pulls `main` itself, builds or reuses the shared `/opt/docketworks/releases/<sha>` release, then for each target instance takes a pre-deploy DB backup, stops runtime services, switches `app` to that release, runs migrations, and restarts its services — you don't run anything per service.

If migrations fail, deploy leaves that instance's services stopped and does not
perform an automatic rollback. Django records successful migrations in the
instance database's `django_migrations` table, so a failed `migrate` can leave
the database partially upgraded. Investigate in the failed release first:

```bash
sudo ./scripts/server/dw-run.sh <client>-<env> python manage.py showmigrations
```

If the right response is rollback rather than fix-forward, run the explicit
rollback command printed by deploy. It is printed only when deploy created a
fresh pre-deploy backup, and restores that paired database backup before
switching the instance back to the matching release:

```bash
sudo ./scripts/predeploy_rollback.sh <client>-<env> <previous-8-char-sha>
```

Deploy builds the previous release before switching, so the code rollback target
always exists for an instance already on shared releases. If deploy was run with
`--no-backup`, no fresh paired database dump exists and deploy will warn instead
of printing a rollback command.

Do not switch only the `app` symlink after a migration failure; old code can
be incompatible with the partially migrated database.

The migration graph was squashed to a fresh baseline (`*_baseline` migrations
with `replaces` lists) in July 2026. A database restored from a dump taken
*before* the squash landed on `main` can only be migrated by a checkout that
predates the squash: the old migration names are no longer addressable, and a
ledger containing only part of the replaced set makes `migrate` abort with
"Django tried to replace migration … but wasn't able to". Restore such dumps
under a pre-squash checkout, migrate to its tip, then deploy forward. Dumps
taken at or after the squash restore and migrate normally — the ledger rides
along and the baseline migrations record themselves automatically.

Release cleanup is part of deploy. The script removes stale incomplete
`.building-*` directories at the start and removes complete releases that are no
longer referenced by any instance `app` symlink or rollback state at the end.
To run only the cleanup pass:

```bash
sudo ./scripts/server/deploy.sh --cleanup-releases
```

**Only if the release changed per-instance config** that `deploy.sh` does not re-render — a new `.env` variable, or a change to the gunicorn systemd unit — also run, once per instance:

```bash
sudo ./scripts/server/instance.sh reconfigure <client> <env>
```

For architecture, see [server_setup.md](server_setup.md); for the exact internal deploy sequence, see [scripts/server/README.md](../scripts/server/README.md).

## Troubleshooting

If you encounter issues after updating:

1. Check the logs:
   - SQL logs: `logs/debug_sql.log`
   - Xero integration: `logs/xero_integration.log`

2. Verify database migrations:

   ```bash
   python manage.py showmigrations workflow
   ```
