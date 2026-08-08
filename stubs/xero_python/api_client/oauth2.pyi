from typing import Any

from xero_python.api_client import ApiClient

class OAuth2Token:
    client_id: str | None
    client_secret: str | None
    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        expiration_buffer: int = 60,
    ) -> None: ...

class TokenApi:
    def __init__(
        self, api_client: ApiClient, client_id: str | None, client_secret: str | None
    ) -> None: ...
    def refresh_token(self, refresh_token: str, scope: list[str]) -> dict[str, Any]: ...
