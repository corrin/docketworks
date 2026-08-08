from typing import Any

import urllib3

class RESTResponse:
    urllib3_response: urllib3.HTTPResponse
    status: int
    reason: str | None
    data: bytes
    def getheaders(self) -> dict[str, str]: ...

class RESTClientObject:
    pool_manager: urllib3.PoolManager
    def __init__(
        self,
        configuration: Any,
        pools_size: int = 4,
        maxsize: int | None = None,
    ) -> None: ...
    # With _preload_content=False the SDK returns the raw urllib3 response
    # (rest.py:240-245); TokenApi's refresh uses that path, so the union is
    # the honest type, not a theoretical one.
    def request(
        self,
        method: str,
        url: str,
        query_params: Any = None,
        headers: Any = None,
        body: Any = None,
        post_params: Any = None,
        _preload_content: bool = True,
        _request_timeout: Any = None,
    ) -> RESTResponse | urllib3.HTTPResponse: ...
