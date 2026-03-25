# Initial Installation Guide

This guide details the steps required to set up the DocketWorks application for local development. The setup involves configuring several external services **before** initializing the application itself. **Xero integration is mandatory** for the application's core functionality.

**Core Dependencies:**

- Python 3.12+
- [Poetry](https://python-poetry.org/)
- MariaDB Server & Client (Version 11.5.2+ recommended)
- [ngrok](https://ngrok.com/) Client

## Defining Your Application Name

To maintain consistency throughout this guide, choose a short client code and environment suffix. For example, if your company is "MSM Sheetmetal", your client code is `msm` and for development the database name would be `dw_msm_dev`.

The naming convention is `dw_<client>_<env>` where:
- `<client>` is your short company code (e.g., `msm`)
- `<env>` is the environment: `dev`, `test`, or `prod`

This will be used to construct:

- Your MariaDB database name (e.g., `dw_msm_dev`)
- Your MariaDB database username (e.g., `dw_msm_dev`)
- Part of your ngrok subdomain (e.g., `docketworks-msm-dev.ngrok-free.app`). Note that ngrok's free tier may not guarantee your requested name, so you might need to tweak it slightly.
- Part of your Xero App name (e.g., `docketworks-msm Development`).

**Decide on your client code now and use it consistently throughout this guide.** We'll refer to the database name as `<db-name>` (e.g., `dw_msm_dev`).

## Phase 1: Prerequisites & External Service Setup

Complete these steps first to gather all necessary credentials and configurations. **Note down the details you create in each step** (passwords, domains, IDs, secrets) as you will need them later.

### Step 1: Install Core Software

Ensure you have installed Python, Poetry, the MariaDB server/client, and the ngrok client on your development machine. Follow the official installation instructions for each tool specific to your operating system.

### Step 2: Set Up MariaDB Database

The application requires a dedicated database and user.

1.  Log into your MariaDB server as root (or another privileged user):
    ```bash
    # Example for Linux/macOS using sudo
    sudo mysql -u root -p
    # Windows might involve opening the MariaDB client/shell directly
    ```
2.  Run the following SQL commands. **Choose a strong password** for the database user and **record it securely**:
    ```sql
    -- Replace <db-name> with your chosen application name
    CREATE DATABASE <db-name>;
    -- Replace <db-name> with your chosen application name
    -- Replace 'your-strong-password' with your chosen password
    CREATE USER '<db-name>'@'localhost' IDENTIFIED BY 'your-strong-password';
    GRANT ALL PRIVILEGES ON <db-name>.* TO '<db-name>'@'localhost';
    FLUSH PRIVILEGES;
    EXIT;
    ```
3.  **Install Timezone Data:** After creating the database, install timezone data into MySQL/MariaDB. This is required for Django's timezone-aware database functions to work correctly:
    ```bash
    # Install timezone data from system zoneinfo files
    sudo mysql_tzinfo_to_sql /usr/share/zoneinfo | sudo mysql mysql
    ```
    - **Details to Record:** Database name (`<db-name>`), DB username (`<db-name>`), DB password (`your-strong-password`).

### Step 3: Set Up ngrok

`ngrok` creates a secure tunnel to your local machine, providing a public HTTPS URL needed for Xero's callbacks.

1.  **Sign up/Log in:** Create an account at [ngrok.com](https://ngrok.com/).
2.  **Install ngrok:** Follow the instructions at [ngrok.com](https://ngrok.com/) to install the ngrok client.
3.  **Get your authtoken:** Find your authtoken in the ngrok dashboard under "Your Authtoken".
4.  **Choose Your Static Domains:** You need predictable hostnames for both backend and frontend.
    - _Free Plan:_ You can use static domains provided on the free tier (e.g., `<db-name>.ngrok-free.app` and `<db-name>-front.ngrok-free.app`). Find this option in your ngrok dashboard.
    - _Paid Plan:_ You can configure custom static domains.
    - **Decide on your domain names now.** You will need them for the Xero setup in the next step.
    - **Details to Record:** Your authtoken and your chosen ngrok static domains for backend and frontend.
5.  **Configure ngrok tunnels:** Copy `ngrok.yml.example` to `ngrok.yml` and fill in your authtoken and domains:
    ```bash
    cp ngrok.yml.example ngrok.yml
    ```
    See [development_session.md](development_session.md) for the command to start tunnels.

### Step 4: Set Up Xero Developer Account & App

The application syncs data with Xero. You need to register a Xero application.

1.  **Sign up/Log in:** Go to the Xero Developer Portal: [https://developer.xero.com/](https://developer.xero.com/) and create an account or log in.
2.  **Create a New App:**
    - Click "New App".
    - Give it a name (e.g., `<db-name> Development`).
    - Select "Web app" as the integration type.
    - Company or Practice Name: Enter your details.
    - **OAuth 2.0 Redirect URI:** This is critical. Enter the URL formed by your ngrok domain from Step 3, followed by `/xero/callback`.
      - Example: `https://<db-name>-dev.ngrok-free.app/xero/callback`
      - _(Make sure to use HTTPS and replace the example domain with your actual ngrok domain)_.
    - Agree to the terms and conditions and create the app.
3.  **Get Credentials:** Once the app is created, navigate to its configuration page.
    - **Details to Record:** Copy the **Client ID** and the **Client Secret**. Keep the Client Secret confidential.

_You should now have recorded: DB credentials, your ngrok domain & region, and your Xero Client ID & Client Secret._

## Phase 2: Application Installation & Configuration

Now that the external services are prepared, set up the application code.

### Step 5: Clone Repository & Install Dependencies

```bash
git clone https://github.com/corrin/docketworks.git
cd docketworks
poetry install
```

### Step 6: Configure Environment (`.env`) File

1.  Copy the example environment file:
    ```bash
    cp .env.example .env # Linux/macOS
    # copy .env.example .env # Windows
    ```
2.  Open the `.env` file in a text editor.
3.  **Populate with Recorded Details:** Fill in the following values using the details you recorded in Phase 1:
    - `DATABASE_URL`: Construct using your DB user, password, and name (e.g., `mysql://<db-name>:your-strong-password@localhost:3306/<db-name>`).
    - `XERO_CLIENT_ID`: Paste your Xero app's Client ID.
    - `XERO_CLIENT_SECRET`: Paste your Xero app's Client Secret.
    - Review other settings and adjust if needed (e.g., `DJANGO_SECRET_KEY` should be changed for any non-local testing).
4.  **Configure Tunnel URLs:** Use the configuration script to set up all tunnel-related environment variables:
    ```bash
    # Replace with your actual backend and frontend ngrok domains
    python scripts/configure_tunnels.py --backend https://<db-name>-dev.ngrok-free.app --frontend https://<db-name>-front.ngrok-free.app
    ```
    This script automatically updates:
    - Backend `.env` file (11 variables including CORS, CSRF, Xero redirect URI, etc.)
    - Frontend `.env` file (API URL and allowed hosts)
    - Frontend `vite.config.ts` (allowed hosts array)

    You can run this script anytime to switch between different tunnel providers (ngrok, localtunnel, etc.).

### Step 7: Initialize Application & Database Schema

1.  Activate the Python virtual environment:
    ```bash
    poetry shell
    ```
2.  Apply database migrations:
    ```bash
    python manage.py migrate
    ```
3.  Load essential configuration and initial data fixtures:

    ```bash
    # Load essential company configuration
    python manage.py loaddata apps/workflow/fixtures/company_defaults.json

    # EITHER
    # Load demo data for development (optional - skip if restoring production data)
    python manage.py loaddata apps/workflow/fixtures/initial_data.json
    # OR...  restore from prod
    python manage.py backport_data_restore

    ```

    **Default Admin Credentials (from initial_data.json):**

    - **Username:** `defaultadmin@example.com`
    - **Password:** `Default-admin-password`

4.  **(Optional) Restore production data:** If you have a production backup to work with:
    ```bash
    python manage.py backport_data_restore restore/prod_backup_YYYYMMDD_HHMMSS.json
    ```
    This loads production data (jobs, timesheets, etc.) while preserving essential configuration. The restore command automatically loads `company_defaults.json` after clearing the database, so you don't need to load it separately.

## Phase 3: Running the Application & Connecting Xero

> **Note:** Steps 8-9 below are needed for initial setup. For subsequent development sessions, see [development_session.md](development_session.md) for the complete daily startup checklist.

### Step 8: Start Ngrok Tunnels

1.  Open a **new, separate terminal window**.
2.  Start tunnels following the instructions in [development_session.md](development_session.md).
3.  Keep this ngrok terminal open. It forwards traffic from your public ngrok URLs to your local development servers (backend on port 8000, frontend on port 5173).

### Step 9: Start Development Server

1.  Go back to your **original terminal window** (where `poetry shell` is active).
2.  Start the Django development server, binding to `0.0.0.0` to accept connections from ngrok:
    ```bash
    python manage.py runserver 0.0.0.0:8000
    # Or specify a different port if 8000 is in use: python manage.py runserver 0.0.0.0:8001
    # (Ensure the port matches the one used in the ngrok command)
    ```

### Step 10: Connect Application to Xero

1.  **Access Application:** Open your web browser and navigate to your public ngrok URL (e.g., `https://<db-name>-dev.ngrok-free.app`).
2.  **Log In:** Use the default admin credentials (`defaultadmin@example.com` / `Default-admin-password`).
3.  **Initiate Xero Connection:** Find the "Connect to Xero" or similar option (likely in Settings/Admin). Click it.
4.  **Authorize in Xero:** You'll be redirected to Xero. Log in if needed. **Crucially, select and authorize the "Demo Company (Global)"**. Do _not_ use your live company data for development.

5.  **Configure Xero tenant:**
    ```bash
    python manage.py xero --setup
    ```
    This fetches your organisation's tenant ID and shortcode.

6.  **Sync data from Xero:**
    ```bash
    python manage.py start_xero_sync
    ```

7.  **Create shop jobs:** (Only if not restoring from production)
    ```bash
    python manage.py create_shop_jobs
    ```

You now have a fully configured local development environment.

## Production-like Setup

For running in a mode closer to production:

1.  Set the environment variable `DJANGO_ENV=production_like` in your `.env` file.
2.  Ensure **Redis** is installed and running (used for caching/Celery). Configure connection details in `.env`.
3.  Start **Celery** worker(s) for handling background tasks (check project specifics).
4.  Run using **Gunicorn** (or another WSGI server):
    ```bash
    gunicorn --bind 0.0.0.0:8000 docketworks.wsgi
    ```
    _(In actual production, this would run behind a reverse proxy like Nginx)._

## Resetting the Database (Wipe and Reload)

To wipe the local database and start fresh:

1.  **Run the reset script** (reads DB name, user, and password from `.env`):

    ```bash
    sudo ./scripts/setup_database.sh --drop
    ```

3.  **Re-install Timezone Data:** (Required for timezone-aware database functions)

    ```bash
    sudo mysql_tzinfo_to_sql /usr/share/zoneinfo | sudo mysql mysql
    ```

4.  **Re-initialize Application:** (Activate `poetry shell` if needed)

    ```bash
    python manage.py migrate
    python manage.py loaddata apps/workflow/fixtures/company_defaults.json
    python manage.py loaddata apps/workflow/fixtures/initial_data.json
    # Optional: python manage.py backport_data_restore restore/prod_backup_YYYYMMDD_HHMMSS.json
    ```

5.  **Re-Connect Xero and Setup:** After resetting, you **must** repeat the Xero connection steps:
    - Log into the app and click "Connect to Xero"
    - Authorize the organisation
    - Run `python manage.py xero --setup`
    - Run `python manage.py start_xero_sync`
    - Run `python manage.py create_shop_jobs` (only if you didn't restore from production)

## Troubleshooting

If you encounter issues:

1.  **Dependencies:** Rerun `poetry install`. Check for errors.
2.  **.env File:** Verify `DATABASE_URL`, Xero keys, `NGROK_DOMAIN`.
3.  **Database:** Is MariaDB running? Do credentials in `.env` match the `CREATE USER` command?
4.  **Migrations:** Run `python manage.py migrate`. Any errors?
5.  **ngrok:** Is the ngrok terminal running without errors? Does the domain match Xero's redirect URI and `.env`? Is the port correct?
6.  **Xero Config:** Double-check Redirect URI in Xero Dev portal. Check Client ID/Secret.
7.  **Django Debug Page/Logs:** Look for detailed errors when `DEBUG=True`. Check `logs/` directory.
