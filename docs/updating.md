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

That's it for a normal code release. `deploy.sh` pulls `main` itself, builds or reuses the shared `/opt/docketworks/releases/<sha>` release, then for each target instance takes a pre-deploy DB backup, switches `current` to that release, runs migrations, and restarts its services — you don't run anything per service.

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
