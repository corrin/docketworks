"""Every route the frontend serves is a navigation target somewhere inside it.

The inverse of the outbound-link probe: that one proves every URL the app
emits resolves, this one proves every URL the app serves can be reached
without typing it. A route can pass its E2E spec by ``page.goto`` and still
be invisible to users — ``/purchasing/po`` and ``/purchasing/stock`` were
served for weeks with nothing in the app linking to them.

Enumeration is structural, the way the link probe's is: the served routes
are every ``createFileRoute('/…')`` under ``src/routes`` with the pathless
layout segments dropped, and the targets are every ``to=`` / ``to:`` /
``href=`` whose value starts with ``/`` anywhere under ``src`` except the
generated route tree, which names every route and would make the check
vacuous. Route files count as sources: a ``redirect()`` in a layout's
``beforeLoad`` and a ``navigate()`` from a sibling route are navigations the
app performs. A parameterised route (``/jobs/$jobId``) is reached by the link
that names its parameter, so both sides keep the ``$param`` spelling and
compare equal.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"

#: Routes the browser lands on from OUTSIDE the app — nothing inside links to
#: them by design. "/" is the entry point; "/reset-password" is reached only
#: by the uid+token link in the reset email (an in-app link without the
#: params would just render its invalid-link state).
ENTRY_ROUTES = frozenset({"/", "/reset-password"})

_ROUTE_RE = re.compile(r"createFileRoute\(\s*'([^']+)'\s*\)")
# to="/x" | to='/x' | to: '/x' | to: "/x" | href="/x" — a value starting with
# "/" is an in-app path; external links start with a scheme and are the link
# probe's business.
_TARGET_RE = re.compile(r"""\b(?:to|href)\s*[=:]\s*\{?\s*["'](/[^"']*)["']""")


def _normalise(path: str) -> str:
    """Drop pathless layout segments (``_authed``) and a trailing slash."""
    segments = [segment for segment in path.split("/") if segment and not segment.startswith("_")]
    return "/" + "/".join(segments)


def served_routes(src: Path = FRONTEND_SRC) -> set[str]:
    """Every URL path a route file declares, minus pathless layouts."""
    routes: set[str] = set()
    for route_file in (src / "routes").rglob("*.tsx"):
        for match in _ROUTE_RE.finditer(route_file.read_text()):
            routes.add(_normalise(match.group(1)))
    return routes


def navigation_targets(src: Path = FRONTEND_SRC) -> set[str]:
    """Every in-app path some link, navigate() or redirect() points at."""
    targets: set[str] = set()
    for source in src.rglob("*.ts*"):
        if source.name == "routeTree.gen.ts":
            continue
        for match in _TARGET_RE.finditer(source.read_text()):
            targets.add(_normalise(match.group(1)))
    return targets


def unreachable_routes(src: Path = FRONTEND_SRC) -> list[str]:
    """Served routes no link or navigate() in the app points at."""
    return sorted(served_routes(src) - navigation_targets(src) - ENTRY_ROUTES)


def main() -> int:
    """Print the unreachable routes; exit non-zero if there are any."""
    unreachable = unreachable_routes()
    for route in unreachable:
        print(f"unreachable: {route}")
    if unreachable:
        print(f"{len(unreachable)} served route(s) have no navigation target in the app")
        return 1
    print(f"every served route is reachable ({len(served_routes())} routes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
