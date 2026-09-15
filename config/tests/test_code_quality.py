"""The code-smell census sees broad contracts without counting prose as debt."""

from pathlib import Path

import pytest

from scripts.checks import code_quality


@pytest.mark.parametrize(
    ("source", "any_count", "object_count"),
    [
        ("def f(x: Any, **kw: object) -> dict[str, Any]: ...", 2, 1),
        ('value: "dict[str, typing.Any | object]"', 1, 1),
        ('value = typing.cast("Any", other)', 1, 0),
        ("type Payload = dict[str, Any | object]", 1, 1),
        ('value: list["object"]', 0, 1),
        ('value: Literal["Any", "object"]', 0, 0),
        ('value: Annotated[object, "Any"]', 0, 1),
        ('"""Any object is prose."""\n# Any object\nvalue = "Any"\nobject()', 0, 0),
    ],
)
def test_broad_contracts_are_visible_without_counting_prose(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    any_count: int,
    object_count: int,
) -> None:
    (tmp_path / "sample.py").write_text(source)
    monkeypatch.setattr(code_quality, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(code_quality, "PYTHON_ROOTS", (".",))
    assert dict(code_quality.measure_broad_types().rows) == {
        "Any annotations": any_count,
        "object annotations": object_count,
    }
