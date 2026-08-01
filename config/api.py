"""The single NinjaAPI instance. One router per domain app, mounted at the exact
v1 URL prefixes. Auth default and exception handlers are added in Phase 1."""

from ninja import NinjaAPI

api = NinjaAPI(
    title="Docketworks API",
    version="2.0.0",
)
