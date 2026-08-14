"""Mint a Google API access token from GCP_CREDENTIALS for manual API calls.

Prints a short-lived bearer token for the raw service account (no Workspace
impersonation) with Drive + Sheets scopes — paste it into curl or an API
explorer when debugging outside the scripts in this package.

Usage:
    GCP_CREDENTIALS=<key.json> uv run python -m scripts.gdocs.get_gapi_token
"""

from google.auth.transport.requests import Request

from scripts.gdocs.gauth import DRIVE_SCOPE, SHEETS_SCOPE, service_account_credentials


def main() -> None:
    """Refresh the service-account credentials and print the access token."""
    creds = service_account_credentials([DRIVE_SCOPE, SHEETS_SCOPE])
    creds.refresh(Request())
    print("Access token:")
    print(creds.token)


if __name__ == "__main__":
    main()
