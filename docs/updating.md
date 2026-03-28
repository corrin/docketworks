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

See [server_setup.md](server_setup.md) for full architecture details.

Deployment is a two-step process:

1. **Merge a PR to `main`** — GitHub Actions (`deploy-uat.yml`) automatically pulls the latest code into `/opt/docketworks/repo` on the server.

2. **Deploy to instances** — SSH into the server and run:

   ```bash
   # All instances
   sudo ./scripts/server/deploy.sh --all

   # Single instance
   sudo ./scripts/server/deploy.sh <name>
   ```

   This updates shared Python/Node deps, then for each instance: builds frontend, runs collectstatic + migrate, restarts Gunicorn.

## Troubleshooting

If you encounter issues after updating:

1. Check the logs:

   - SQL logs: `logs/debug_sql.log`
   - Xero integration: `logs/xero_integration.log`

2. Verify database migrations:

   ```bash
   python manage.py showmigrations workflow
   ```
