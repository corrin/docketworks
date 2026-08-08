from typing import Any

from xero_python.api_client.oauth2 import OAuth2Token

class Configuration:
    oauth2_token: OAuth2Token | None
    debug: bool
    temp_folder_path: str | None
    cert_file: Any
    key_file: Any
    def __init__(self, debug: bool = False, oauth2_token: OAuth2Token | None = None) -> None: ...
