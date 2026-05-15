from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


class Celery:
    conf: Any

    def __init__(self, *args: Any, **kwargs: Any) -> None: ...
    def config_from_object(self, *args: Any, **kwargs: Any) -> None: ...
    def autodiscover_tasks(self, *args: Any, **kwargs: Any) -> None: ...


def shared_task(*args: Any, **kwargs: Any) -> Callable[[F], F]: ...
