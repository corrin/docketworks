from collections.abc import Callable
from typing import Any, TypeVar, overload

F = TypeVar("F", bound=Callable[..., Any])


class Signal:
    @overload
    def connect(self, receiver: F, **kwargs: Any) -> F: ...
    @overload
    def connect(self, receiver: None = None, **kwargs: Any) -> Callable[[F], F]: ...


task_unknown: Signal
