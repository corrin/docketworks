from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


class Signal:
    def connect(self, receiver: F | None = None, **kwargs: Any) -> F: ...


task_unknown: Signal
