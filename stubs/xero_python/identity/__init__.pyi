from typing import Any

from xero_python.api_client import ApiClient

class Connection:
    tenant_id: str | None
    tenant_name: str | None
    tenant_type: str | None
    def __init__(self, **kwargs: Any) -> None: ...

class IdentityApi:
    def __init__(self, api_client: ApiClient) -> None: ...
    def get_connections(self, **kwargs: Any) -> list[Connection]: ...
