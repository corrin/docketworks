"""Local nplusone integration tweaks.

The detector uses Blinker weak refs for bound-method receivers by default.
Under the Django request middleware those listeners already have an explicit
teardown path, so weak cleanup is unnecessary and can emit ignored cleanup
tracebacks while Blinker mutates its internal receiver maps.
"""

from __future__ import annotations

from typing import Any

from nplusone.core import listeners, signals
from nplusone.core.stack import get_caller
from nplusone.ext.django.middleware import NPlusOneMiddleware


class StrongLazyListener(listeners.LazyListener):
    """Lazy-load detector with explicit, non-weak signal registrations."""

    def setup(self) -> None:
        self.loaded: set[str] = set()
        self.ignored: set[str] = set()
        worker = signals.get_worker()
        signals.load.connect(self.handle_load, sender=worker, weak=False)
        signals.ignore_load.connect(self.handle_ignore, sender=worker, weak=False)
        signals.lazy_load.connect(self.handle_lazy, sender=worker, weak=False)

    def cleanup(self) -> None:
        signals.load.disconnect(self.handle_load)
        signals.ignore_load.disconnect(self.handle_ignore)
        signals.lazy_load.disconnect(self.handle_lazy)


class StrongEagerListener(listeners.EagerListener):
    """Eager-load detector with explicit, non-weak signal registrations."""

    def setup(self) -> None:
        signals.eager_load.connect(
            self.handle_eager,
            sender=signals.get_worker(),
            weak=False,
        )
        self.tracker = listeners.EagerTracker()
        self.touched: list[tuple[type, str, list[str]] | None] = []

    def handle_eager(
        self,
        caller: Any,
        args: tuple[Any, ...] | None = None,
        kwargs: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        ret: Any = None,
        parser: Any = None,
    ) -> None:
        model, field, instances, key = parser(args, kwargs, context)
        frame = get_caller()
        self.tracker.track(model, field, instances, key, caller=frame)
        signals.touch.connect(
            self.handle_touch,
            sender=signals.get_worker(),
            weak=False,
        )

    def cleanup(self) -> None:
        signals.eager_load.disconnect(self.handle_eager)
        signals.touch.disconnect(self.handle_touch)


class StrongDebugListener(listeners.DebugListener):
    """Debug listener with explicit, non-weak signal registrations."""

    def setup(self) -> None:
        worker = signals.get_worker()
        signals.load.connect(self._on_load, sender=worker, weak=False)
        signals.ignore_load.connect(self._on_ignore_load, sender=worker, weak=False)
        signals.lazy_load.connect(self._on_lazy_load, sender=worker, weak=False)
        signals.eager_load.connect(self._on_eager_load, sender=worker, weak=False)
        signals.touch.connect(self._on_touch, sender=worker, weak=False)

    def cleanup(self) -> None:
        signals.load.disconnect(self._on_load)
        signals.ignore_load.disconnect(self._on_ignore_load)
        signals.lazy_load.disconnect(self._on_lazy_load)
        signals.eager_load.disconnect(self._on_eager_load)
        signals.touch.disconnect(self._on_touch)


def install_strong_nplusone_listeners() -> None:
    """Use strong nplusone listeners while preserving explicit teardown."""

    listeners.listeners["lazy_load"] = StrongLazyListener
    listeners.listeners["eager_load"] = StrongEagerListener
    listeners.DebugListener = StrongDebugListener


class StrongNPlusOneMiddleware(NPlusOneMiddleware):
    """Nplusone middleware without weakref receiver cleanup noise."""

def process_request(self, request: Any) -> Any:
    install_strong_nplusone_listeners()
    return super().process_request(request)
