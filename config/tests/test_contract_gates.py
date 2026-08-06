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
    """Load a script from scripts/ as a module without executing main().

    Imported rather than run as a subprocess, so these tests exercise the same
    module CI runs: a rename or a signature change breaks them instead of
    silently passing against a copied snapshot of the gate.
    """
    path = REPO_ROOT / "scripts" / f"{name}.py"
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


@pytest.fixture
def parity() -> ModuleType:
    return _load_script("schema_parity_diff")


NULLABLE_SPELLINGS = [
    pytest.param({"type": "string", "nullable": True}, True, id="v1-3.0-nullable-flag"),
    pytest.param({"anyOf": [{"type": "string"}, {"type": "null"}]}, True, id="v2-3.1-anyOf"),
    pytest.param({"oneOf": [{"type": "string"}, {"type": "null"}]}, True, id="oneOf"),
    pytest.param({"type": ["string", "null"]}, True, id="3.1-type-list"),
    pytest.param({"type": "string"}, False, id="plain-string"),
    pytest.param({"type": "string", "nullable": False}, False, id="explicit-not-nullable"),
    # allOf means "satisfies EVERY branch", so a null branch inside one cannot
    # make the whole nullable. Treating it as if it did would invent gaps.
    pytest.param({"allOf": [{"type": "string"}, {"type": "null"}]}, False, id="allOf-not-nullable"),
]


@pytest.mark.parametrize(("node", "expected"), NULLABLE_SPELLINGS)
def test_is_nullable_reads_both_schema_dialects(
    parity: ModuleType, node: dict[str, object], expected: bool
) -> None:
    """v1 is OpenAPI 3.0, v2 is 3.1; reading one dialect misreports the other."""
    assert parity._is_nullable({}, node) is expected


def test_is_uuid_sees_through_a_nullable_union(parity: ModuleType) -> None:
    """The bug that made 200 of 216 findings false positives on the first pass."""
    nullable_uuid = {"anyOf": [{"type": "string", "format": "uuid"}, {"type": "null"}]}
    assert parity._is_uuid({}, nullable_uuid) is True
    assert parity._is_uuid({}, {"type": "string"}) is False


def test_deref_follows_a_local_pointer(parity: ModuleType) -> None:
    spec = {"components": {"schemas": {"Job": {"type": "object"}}}}
    assert parity._deref(spec, {"$ref": "#/components/schemas/Job"}) == {"type": "object"}


def test_deref_returns_empty_on_a_cycle_but_raises_on_a_bad_pointer(parity: ModuleType) -> None:
    """Cycles are expected (a Job carries events carrying a job); typos are not.

    An unresolvable pointer used to resolve to {}, which made the walker report
    zero properties and silently under-report every gap beneath it.
    """
    cyclic = {"components": {"schemas": {"Job": {"$ref": "#/components/schemas/Job"}}}}
    assert parity._deref(cyclic, {"$ref": "#/components/schemas/Job"}) == {}

    with pytest.raises(KeyError, match="Unresolvable"):
        parity._deref({"components": {"schemas": {}}}, {"$ref": "#/components/schemas/Missing"})
    with pytest.raises(ValueError, match="non-local"):
        parity._deref({}, {"$ref": "https://example.test/schema.json#/Job"})


def test_walk_properties_records_required_against_the_declaring_parent(
    parity: ModuleType,
) -> None:
    schema = {
        "type": "object",
        "required": ["id"],
        "properties": {
            "id": {"type": "string"},
            "child": {
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string"}, "note": {"type": "string"}},
            },
        },
    }
    found = parity._walk_properties({}, schema)
    assert found[("id",)].required is True
    assert found[("child",)].required is False
    assert found[("child", "name")].required is True
    assert found[("child", "note")].required is False


def test_path_parameter_slots_come_from_the_url_not_the_array_order(
    parity: ModuleType,
) -> None:
    """OpenAPI binds a path parameter to its placeholder by name, not by index.

    v1 exercises that freedom on 11 operations — `/api/job/jobs/{job_id}/
    files/{file_id}/` lists them file_id, job_id — so keying by array index
    compared v1's file_id against v2's job_id. It produced no wrong gap only
    because both are uuids there; a route mixing an int and a uuid slot would
    have reported a phantom regression.
    """
    operation = parity.Operation(
        "/x/{second}/{first}/",
        {
            "parameters": [
                {"name": "first", "in": "path", "schema": {"type": "string", "format": "uuid"}},
                {"name": "second", "in": "path", "schema": {"type": "integer"}},
            ]
        },
    )
    found = parity._parameters({}, operation)
    assert found[("path-param", "0")].schema["type"] == "integer"
    assert found[("path-param", "1")].schema["format"] == "uuid"


def test_path_parameter_not_matching_any_placeholder_raises(parity: ModuleType) -> None:
    """A parameter naming no placeholder is a malformed schema, not a slot."""
    operation = parity.Operation(
        "/x/{id}/", {"parameters": [{"name": "nope", "in": "path", "schema": {"type": "string"}}]}
    )
    with pytest.raises(ValueError, match="matches no placeholder"):
        parity._parameters({}, operation)


def test_unrecorded_gap_is_a_new_regression(parity: ModuleType) -> None:
    drift = parity._apply_gap_ratchet(
        live={"nullable GET /x/ :: response:200.a", "uuid GET /x/ :: response:200.b"},
        recorded={"nullable GET /x/ :: response:200.a"},
        update=False,
    )
    assert len(drift) == 1
    assert "NEW contract regression" in drift[0]
    assert "response:200.b" in drift[0]


def test_recorded_gap_that_no_longer_exists_also_fails(parity: ModuleType) -> None:
    """Without this the file becomes a wishlist: entries go in and never leave."""
    drift = parity._apply_gap_ratchet(
        live=set(),
        recorded={"nullable GET /x/ :: response:200.a"},
        update=False,
    )
    assert len(drift) == 1
    assert "no longer present" in drift[0]


def test_matching_sets_are_clean(parity: ModuleType) -> None:
    gaps = {"nullable GET /x/ :: response:200.a"}
    assert parity._apply_gap_ratchet(live=gaps, recorded=gaps, update=False) == []


def test_missing_record_file_raises_rather_than_reporting_every_gap_as_new(
    parity: ModuleType, tmp_path: Path
) -> None:
    """An absent file would otherwise relabel all 176 known gaps as regressions."""
    with pytest.raises(FileNotFoundError, match="Create it containing only its header"):
        parity._read_record_file(tmp_path / "absent.txt")


def test_missing_file_message_does_not_promise_that_update_baseline_fixes_it(
    parity: ModuleType, tmp_path: Path
) -> None:
    """`main()` reads the file to build an argument, so the read precedes `update`.

    An earlier message said "regenerate it with --update-baseline", which sends
    the reader down a path that fails identically. Pinned because the remedy is
    the kind of prose that drifts back (ADR 0038).
    """
    with pytest.raises(FileNotFoundError) as raised:
        parity._read_record_file(tmp_path / "absent.txt")
    assert "regenerate it with --update-baseline" not in str(raised.value)


def test_indented_comment_is_not_read_as_an_entry(parity: ModuleType, tmp_path: Path) -> None:
    record = tmp_path / "gaps.txt"
    record.write_text("# header\n   # indented comment\n\nnullable GET /x/ :: response:200.a\n")
    assert parity._read_record_file(record) == {"nullable GET /x/ :: response:200.a"}
