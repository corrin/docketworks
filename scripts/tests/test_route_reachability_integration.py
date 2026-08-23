"""Every route the app serves is reachable from inside the app.

The slow-tier counterpart of the outbound-link probe, picked up by
``./scripts/ops/run_integration_tests.sh`` through the ``integration`` marker
and run before merge. Static over the frontend source rather than a browser
crawl: the question is whether a navigation target exists, and the route
files and the links are both in the tree.
"""

import pytest

from scripts.checks.route_reachability import served_routes, unreachable_routes

pytestmark = pytest.mark.integration


def test_every_served_route_has_a_navigation_target() -> None:
    assert served_routes(), "no routes found — is frontend/src/routes where the router lives?"
    assert unreachable_routes() == []
