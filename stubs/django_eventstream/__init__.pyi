# Stub file for django-eventstream (ships no py.typed). Only the surface this
# codebase calls is declared; the rest of the package stays unannotated.
from collections.abc import Sequence

def send_event(
    channel: str,
    event_type: str,
    data: object,
    skip_user_ids: Sequence[str] | None = ...,
    async_publish: bool = ...,
    json_encode: bool = ...,
) -> None: ...
