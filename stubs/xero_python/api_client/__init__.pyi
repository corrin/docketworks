from collections.abc import Callable
from typing import Any

from xero_python.api_client.configuration import Configuration as Configuration
from xero_python.rest import RESTClientObject

class ApiClient:
    configuration: Configuration
    rest_client: RESTClientObject
    def __init__(
        self,
        configuration: Configuration | None = None,
        header_name: str | None = None,
        header_value: str | None = None,
        cookie: str | None = None,
        pool_threads: int | None = None,
        oauth2_token_saver: Callable[[dict[str, Any]], None] | None = None,
        oauth2_token_getter: Callable[[], dict[str, Any] | None] | None = None,
    ) -> None: ...
    def set_oauth2_token(self, token: dict[str, Any]) -> None: ...
    def oauth2_token_getter(
        self, token_getter: Callable[[], dict[str, Any] | None]
    ) -> Callable[[], dict[str, Any] | None]: ...
    def oauth2_token_saver(
        self, token_saver: Callable[[dict[str, Any]], None]
    ) -> Callable[[dict[str, Any]], None]: ...
