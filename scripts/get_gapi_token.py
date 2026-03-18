import os

from google.auth.transport.requests import Request
from google.oauth2 import service_account

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]

key_file = os.getenv("GCP_CREDENTIALS")
if not key_file:
    raise RuntimeError("GCP_CREDENTIALS environment variable not set")
if not os.path.exists(key_file):
    raise RuntimeError(f"Google service account key file not found: {key_file}")

creds = service_account.Credentials.from_service_account_file(key_file, scopes=SCOPES)
creds.refresh(Request())
print("Access token:")
print(creds.token)
