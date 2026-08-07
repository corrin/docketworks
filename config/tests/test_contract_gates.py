"""Guards on the two gates that stop contract and duplication rot.

Both gates are ratchets, and a ratchet nobody has tried to break is a
decoration. The regression they exist to prevent is silent by construction —
nobody chooses a weaker type or writes a second implementation on purpose, so
the only evidence either gate works is that it is shown failing.

These tests therefore mutate in BOTH directions. For the contract ratchet that
means an unrecorded gap must fail (a new regression) and a recorded gap that no
longer exists must also fail (otherwise the file rots into a wishlist that
never shrinks). For the duplication gate it means each shape it claims to catch
is caught, and each exemption it claims to grant is granted — an exemption that
silently over-matches would disable the gate without failing anything.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_script(name: str) -> ModuleType:
    """Load a gate from scripts/checks/ as a module without executing main().

    Imported rather than run as a subprocess, so these tests exercise the same
    module CI runs: a rename or a signature change breaks them instead of
    silently passing against a copied snapshot of the gate.

    By path rather than importlib.import_module, which would cache: each test
    monkeypatches module-level constants, and a shared module would leak that
    between them.
    """
    path = REPO_ROOT / "scripts" / "checks" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def apps_tree(tmp_path: Path) -> Path:
    apps_root = tmp_path / "apps"
    (apps_root / "billing" / "services").mkdir(parents=True)
    (apps_root / "billing" / "__init__.py").write_text("")
    (apps_root / "billing" / "services" / "__init__.py").write_text("")
    return apps_root


@pytest.fixture
def duplicates(apps_tree: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    module = _load_script("find_duplicates")
    monkeypatch.setattr(module, "APPS", apps_tree)
    monkeypatch.setattr(module, "REPO", apps_tree.parent)
    return module


def test_clean_tree_passes(apps_tree: Path, duplicates: ModuleType) -> None:
    (apps_tree / "billing" / "api.py").write_text("def charge() -> None:\n    pass\n")
    assert duplicates.main() == 0


def test_same_symbol_in_two_modules_fails(
    apps_tree: Path, duplicates: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    (apps_tree / "billing" / "one.py").write_text("class Invoice:\n    pass\n")
    (apps_tree / "billing" / "two.py").write_text("class Invoice:\n    pass\n")
    assert duplicates.main() == 1
    assert "'Invoice' is defined in 2 modules" in capsys.readouterr().out


def test_api_handler_beside_its_service_is_exempt(apps_tree: Path, duplicates: ModuleType) -> None:
    """The layering this codebase mandates is not duplication (13 real pairs)."""
    (apps_tree / "billing" / "api.py").write_text("def charge() -> None:\n    pass\n")
    (apps_tree / "billing" / "services" / "charging.py").write_text(
        "def charge() -> None:\n    pass\n"
    )
    assert duplicates.main() == 0


def test_exemption_does_not_span_apps(
    apps_tree: Path, duplicates: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """An api.py in one app does not excuse a same-named service in another."""
    (apps_tree / "payroll" / "services").mkdir(parents=True)
    (apps_tree / "billing" / "api.py").write_text("def charge() -> None:\n    pass\n")
    (apps_tree / "payroll" / "services" / "charging.py").write_text(
        "def charge() -> None:\n    pass\n"
    )
    assert duplicates.main() == 1
    assert "'charge' is defined in 2 modules" in capsys.readouterr().out


def test_services_api_py_does_not_exempt_everything(
    apps_tree: Path, duplicates: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """`<app>/services/api.py` matches BOTH halves of the exemption.

    It is named api.py and it sits under services/, so a naive predicate found
    one handler and one service, compared that single path's app to itself,
    and exempted whatever it was paired with — in any app. That turns the one
    exemption carrying the whole check into a blanket pass.
    """
    (apps_tree / "payroll").mkdir(parents=True)
    (apps_tree / "billing" / "services" / "api.py").write_text("class Invoice:\n    pass\n")
    (apps_tree / "payroll" / "models.py").write_text("class Invoice:\n    pass\n")
    assert duplicates.main() == 1
    assert "'Invoice' is defined in 2 modules" in capsys.readouterr().out


def test_sibling_module_fails(
    apps_tree: Path, duplicates: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """v1's actual pathology: job_rest_service.py beside job_service.py."""
    (apps_tree / "billing" / "services" / "job_service.py").write_text("x = 1\n")
    (apps_tree / "billing" / "services" / "job_rest_service.py").write_text("y = 2\n")
    assert duplicates.main() == 1
    assert "is a sibling of" in capsys.readouterr().out


def test_sibling_check_is_per_directory_not_per_bare_stem(
    apps_tree: Path, duplicates: ModuleType
) -> None:
    """`urls_rest.py` in one app is not a sibling of `urls.py` in another.

    Guards the collapse this check originally had: keying every module by its
    bare stem kept one arbitrary survivor per name, so `apps.py` (15 copies in
    v2) and `urls.py` (8) shadowed each other. That both hid real pairs and
    would invent cross-app ones.
    """
    (apps_tree / "payroll").mkdir(parents=True)
    (apps_tree / "billing" / "urls.py").write_text("x = 1\n")
    (apps_tree / "payroll" / "urls_rest.py").write_text("y = 2\n")
    assert duplicates.main() == 0


def test_sibling_pairs_in_several_directories_are_all_reported(
    apps_tree: Path, duplicates: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """v1 has four such pairs; a per-stem map reported one of them."""
    (apps_tree / "payroll").mkdir(parents=True)
    for app in ("billing", "payroll"):
        (apps_tree / app / "urls.py").write_text("x = 1\n")
        (apps_tree / app / "urls_rest.py").write_text("y = 2\n")
    assert duplicates.main() == 1
    assert capsys.readouterr().out.count("is a sibling of") == 2


def test_management_commands_may_all_define_command(
    apps_tree: Path, duplicates: ModuleType
) -> None:
    """Django requires the class be named Command; that is not duplication."""
    for app in ("billing", "payroll"):
        commands = apps_tree / app / "management" / "commands"
        commands.mkdir(parents=True)
        (commands / "do_thing.py").write_text("class Command:\n    pass\n")
    assert duplicates.main() == 0


def test_command_exemption_does_not_cover_ordinary_modules(
    apps_tree: Path, duplicates: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """The path test looks for both segments; a stray `commands/` must not excuse a duplicate.

    Without this, any directory named `commands` anywhere under a path that
    also contains `management` would silently leave the gate — the
    over-matching exemption these tests exist to catch.
    """
    (apps_tree / "billing" / "commands").mkdir(parents=True)
    (apps_tree / "billing" / "commands" / "runner.py").write_text("class Job:\n    pass\n")
    (apps_tree / "billing" / "other.py").write_text("class Job:\n    pass\n")
    assert duplicates.main() == 1
    assert "'Job' is defined in 2 modules" in capsys.readouterr().out
