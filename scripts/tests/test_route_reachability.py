"""The route-reachability check's enumeration, on a fake frontend tree."""

from pathlib import Path

from scripts.checks.route_reachability import (
    navigation_targets,
    served_routes,
    unreachable_routes,
)


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _frontend(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    _write(src, "routes/__root.tsx", "export const Route = createRootRoute()")
    _write(src, "routes/index.tsx", "createFileRoute('/')")
    _write(src, "routes/_authed.tsx", "createFileRoute('/_authed')")
    _write(src, "routes/_authed/kanban.tsx", "createFileRoute('/_authed/kanban')")
    _write(
        src, "routes/_authed/purchasing/po/index.tsx", "createFileRoute('/_authed/purchasing/po/')"
    )
    _write(
        src,
        "routes/_authed/purchasing/po/$poId.tsx",
        "createFileRoute('/_authed/purchasing/po/$poId')",
    )
    _write(
        src, "routes/_authed/purchasing/stock.tsx", "createFileRoute('/_authed/purchasing/stock')"
    )
    _write(src, "routeTree.gen.ts", "// generated: to: '/_authed/purchasing/stock'")
    _write(
        src,
        "features/shell/AppNavbar.tsx",
        """<NavMenuLink to="/kanban">Board</NavMenuLink>
           <Link to="/purchasing/po/$poId" params={{ poId }}>PO</Link>
           <a href="https://go.xero.com/x">Xero</a>""",
    )
    _write(src, "features/purchasing/PoListPage.tsx", "navigate({ to: '/purchasing/po' })")
    _write(src, "routes/_authed/timesheets/daily.tsx", "throw redirect({ to: '/kanban' })")
    return src


def test_served_routes_drop_pathless_layouts_and_trailing_slashes(tmp_path: Path) -> None:
    """A layout segment is not a URL, and an index route is its parent's path."""
    assert served_routes(_frontend(tmp_path)) == {
        "/",
        "/kanban",
        "/purchasing/po",
        "/purchasing/po/$poId",
        "/purchasing/stock",
    }


def test_targets_come_from_links_and_navigations_but_never_the_generated_tree(
    tmp_path: Path,
) -> None:
    """A redirect in a route file is a navigation the app performs; the generated route
    tree names every route and would make the check vacuous."""
    assert navigation_targets(_frontend(tmp_path)) == {
        "/kanban",
        "/purchasing/po/$poId",
        "/purchasing/po",
    }


def test_a_served_route_nothing_links_to_is_unreachable(tmp_path: Path) -> None:
    """Use Stock is served and specced, and a user cannot get there."""
    assert unreachable_routes(_frontend(tmp_path)) == ["/purchasing/stock"]


def test_the_entry_route_is_exempt(tmp_path: Path) -> None:
    """Nothing links to '/'; the browser lands on it."""
    assert "/" not in unreachable_routes(_frontend(tmp_path))
