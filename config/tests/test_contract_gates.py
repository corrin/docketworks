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
import yaml

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


# --- the status table: derived counts, and the prose that quotes them ---------
#
# The rows that move as the port progresses are derived rather than typed, and
# two failures matter that no reviewer reliably sees. A v2 rename nobody records
# corrupts the remaining count in BOTH directions — the v1 name reads unported,
# the v2 name looks new — and prose quoting a number the table no longer says is
# the same staleness one line further down. Both are planted here, because the
# regeneration path passing proves only that the happy case works.


@pytest.fixture
def status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """The gate against a miniature repo: three called operations, one served."""
    module = _load_script("status_table")

    v1 = tmp_path / "v1-frontend-operations.yml"
    v1.write_text(
        "e2e_spec_files: 7\n"
        "operations: [alpha_list, beta_list, gamma_list, dead_list]\n"
        "called: [alpha_list, beta_list, gamma_list]\n"
        "renamed: {}\n"
        "introduced: []\n"
    )
    schema = tmp_path / "schema.v2.yml"
    schema.write_text("      operationId: alpha_list\n")

    monkeypatch.setattr(module, "V1_OPERATIONS_FILE", v1)
    monkeypatch.setattr(module, "V2_SCHEMA", schema)
    monkeypatch.setattr(module, "STATUS_DOC", tmp_path / "rewrite-status.md")
    # Only the row under test, so these stay about the derivation rather than
    # about which rows the real doc happens to carry.
    label = "Backend operations still to port"
    monkeypatch.setattr(module, "MEASURED", {label: module.MEASURED[label]})
    return module


def _write_doc(status: ModuleType, *, prose: str = "", unported: int = 2, dead: int = 1) -> None:
    status.STATUS_DOC.write_text(
        "# Rewrite status\n\n"
        "| Measure | Value |\n"
        "|---|---|\n"
        f"| Backend operations still to port | **{unported}** (see below; {dead} more "
        "exist but nothing calls them) |\n"
        "\n" + prose
    )


def test_unported_is_derived_from_v2s_live_schema(status: ModuleType) -> None:
    """Three called, one served by v2, so two remain. Nobody types this number."""
    assert status._measure_unported() == "**2** (see below; 1 more exist but nothing calls them)"


def test_porting_an_operation_lowers_the_count_with_no_file_edit(status: ModuleType) -> None:
    """The whole point: progress moves the number, not a person."""
    status.V2_SCHEMA.write_text("      operationId: alpha_list\n      operationId: beta_list\n")
    assert status._measure_unported().startswith("**1**")


def test_a_recorded_rename_counts_as_ported(status: ModuleType) -> None:
    status.V1_OPERATIONS_FILE.write_text(
        "e2e_spec_files: 7\n"
        "operations: [alpha_list, beta_list, gamma_list, dead_list]\n"
        "called: [alpha_list, beta_list, gamma_list]\n"
        "renamed: {beta_list: renamed_beta_list}\n"
        "introduced: []\n"
    )
    status.V2_SCHEMA.write_text(
        "      operationId: alpha_list\n      operationId: renamed_beta_list\n"
    )
    assert status._measure_unported().startswith("**1**")


def test_an_unrecorded_rename_fails_the_gate(
    status: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """The one staleness detectable without the v1 repo, which CI cannot see."""
    status.V2_SCHEMA.write_text("      operationId: alpha_list\n      operationId: surprise_list\n")
    _write_doc(status)
    assert status.main() == 1
    assert "surprise_list" in capsys.readouterr().err


def test_an_operation_declared_new_is_allowed(status: ModuleType) -> None:
    """v2 may add endpoints v1 never had; it just has to say so."""
    status.V1_OPERATIONS_FILE.write_text(
        "e2e_spec_files: 7\n"
        "operations: [alpha_list, beta_list, gamma_list, dead_list]\n"
        "called: [alpha_list, beta_list, gamma_list]\n"
        "renamed: {}\n"
        "introduced: [surprise_list]\n"
    )
    status.V2_SCHEMA.write_text("      operationId: alpha_list\n      operationId: surprise_list\n")
    assert status.orphan_v2_operations() == set()


def test_prose_quoting_the_wrong_number_fails(
    status: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """The table owns the number; a sentence disagreeing with it is the rot."""
    _write_doc(status, prose="v1's frontend calls them; **97 of them are unported**.\n")
    assert status.main() == 1
    error = capsys.readouterr().err
    assert "97" in error and "unported" in error


def test_prose_quoting_the_right_number_passes(status: ModuleType) -> None:
    _write_doc(status, prose="Measured today, **2 are unported** and grouped below.\n")
    assert status.main() == 0


def test_the_row_does_not_fail_against_its_own_phrase(status: ModuleType) -> None:
    """The table row contains both the phrase and the number; it is the source, not a claim."""
    _write_doc(status)
    assert status.main() == 0


def test_prose_is_checked_against_the_regenerated_value_not_the_stale_one(
    status: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """A rewrite run must not leave prose agreeing with the number it just replaced.

    Without this the two drift apart in the one moment they are guaranteed to be
    read together — the run that fixes the row.
    """
    _write_doc(status, prose="**5 are unported**.\n", unported=5)
    assert status.main() == 1
    assert "says 5" in capsys.readouterr().err


# --- the response-presence gate ------------------------------------------
#
# It walks $refs, so the ways to slip past it are all structural: a schema that
# is only reachable indirectly, or reachable by a route the walk does not
# follow. Each test below is one such route.


@pytest.fixture
def export(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """The exporter, with Django boot suppressed — these tests build specs by hand."""
    monkeypatch.setattr("django.setup", lambda: None)
    return _load_script("export_openapi")


def _spec(schemas: dict[str, object], responses: object) -> dict[str, object]:
    return {
        "paths": {"/api/thing/": {"get": {"responses": responses}}},
        "components": {"schemas": schemas},
    }


LOOSE = {"properties": {"a": {"type": "string"}}, "required": []}
TIGHT = {"properties": {"a": {"type": "string"}}, "required": ["a"]}
REF = "#/components/schemas/Loose"


def test_a_tight_response_schema_passes(export: ModuleType) -> None:
    spec = _spec(
        {"Tight": TIGHT},
        {
            "200": {
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Tight"}}}
            }
        },
    )

    assert export.optional_response_properties(spec) == {}


def test_an_optional_response_property_fails(export: ModuleType) -> None:
    spec = _spec(
        {"Loose": LOOSE}, {"200": {"content": {"application/json": {"schema": {"$ref": REF}}}}}
    )

    assert export.optional_response_properties(spec) == {"Loose": ["a"]}


def test_a_request_only_schema_is_not_flagged(export: ModuleType) -> None:
    """Optional is correct on the way in; flagging it would make the gate noise."""
    spec = {
        "paths": {
            "/api/thing/": {
                "post": {
                    "requestBody": {"content": {"application/json": {"schema": {"$ref": REF}}}},
                    "responses": {"204": {}},
                }
            }
        },
        "components": {"schemas": {"Loose": LOOSE}},
    }

    assert export.optional_response_properties(spec) == {}


def test_a_schema_reached_only_through_an_array_is_flagged(export: ModuleType) -> None:
    """A list endpoint refs its item schema through `items`, never directly."""
    spec = _spec(
        {"Loose": LOOSE},
        {
            "200": {
                "content": {
                    "application/json": {"schema": {"type": "array", "items": {"$ref": REF}}}
                }
            }
        },
    )

    assert export.optional_response_properties(spec) == {"Loose": ["a"]}


def test_a_schema_nested_two_levels_deep_is_flagged(export: ModuleType) -> None:
    """The walk is transitive, so a leaf schema cannot hide behind a tight parent."""
    outer = {"properties": {"inner": {"$ref": REF}}, "required": ["inner"]}
    spec = _spec(
        {"Outer": outer, "Loose": LOOSE},
        {
            "200": {
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Outer"}}}
            }
        },
    )

    assert export.optional_response_properties(spec) == {"Loose": ["a"]}


def test_a_schema_reached_through_anyof_is_flagged(export: ModuleType) -> None:
    """A nullable object property is an anyOf, which is how most refs appear."""
    outer = {
        "properties": {"inner": {"anyOf": [{"$ref": REF}, {"type": "null"}]}},
        "required": ["inner"],
    }
    spec = _spec(
        {"Outer": outer, "Loose": LOOSE},
        {
            "200": {
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Outer"}}}
            }
        },
    )

    assert export.optional_response_properties(spec) == {"Loose": ["a"]}


def test_a_missing_required_key_is_treated_as_none_required(export: ModuleType) -> None:
    """Pydantic omits `required` entirely when nothing is required."""
    spec = _spec(
        {"Loose": {"properties": {"a": {"type": "string"}}}},
        {"200": {"content": {"application/json": {"schema": {"$ref": REF}}}}},
    )

    assert export.optional_response_properties(spec) == {"Loose": ["a"]}


def test_only_the_missing_properties_are_reported(export: ModuleType) -> None:
    partial = {"properties": {"a": {}, "b": {}, "c": {}}, "required": ["b"]}
    spec = _spec(
        {"Loose": partial}, {"200": {"content": {"application/json": {"schema": {"$ref": REF}}}}}
    )

    assert export.optional_response_properties(spec) == {"Loose": ["a", "c"]}


def test_a_schema_with_no_properties_is_skipped(export: ModuleType) -> None:
    """An empty 204 body or a free-form object has nothing to require."""
    spec = _spec(
        {"Loose": {"type": "object"}},
        {"200": {"content": {"application/json": {"schema": {"$ref": REF}}}}},
    )

    assert export.optional_response_properties(spec) == {}


def test_an_error_response_is_walked_too(export: ModuleType) -> None:
    """422 bodies are responses; a loose error shape costs the same branch."""
    spec = _spec(
        {"Loose": LOOSE}, {"422": {"content": {"application/json": {"schema": {"$ref": REF}}}}}
    )

    assert export.optional_response_properties(spec) == {"Loose": ["a"]}


def test_the_live_schema_has_no_optional_response_properties(export: ModuleType) -> None:
    """The gate's real subject. Pinned at zero, so this is the ratchet itself."""
    spec = yaml.safe_load((REPO_ROOT / "frontend" / "schema.v2.yml").read_text())

    assert export.optional_response_properties(spec) == {}
