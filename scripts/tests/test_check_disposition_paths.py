"""Attack the disposition gate: prove it fails when it should.

A gate is only worth its runtime if a wrong record actually turns it red. The
first version of this check passed on a suffix allowlist that silently skipped
a dozen real rows — it reported success over a smaller check than it appeared
to run, which is precisely the failure the check exists to prevent elsewhere.
So the cases below are mostly about what it must NOT wave through.
"""

from pathlib import Path

from scripts.checks.check_disposition_paths import audit

_HEADER = "| v1 | disposition | v2 |\n| --- | --- | --- |\n"


def _row(v2: str) -> str:
    return f"| something | ported | `{v2}` |\n"


class TestMissingPaths:
    def test_a_ported_path_that_does_not_exist_is_reported(self, tmp_path: Path) -> None:
        """The whole point: a record claiming a port that is not there."""
        result = audit(_HEADER + _row("apps/gone/service.py"), tmp_path)

        assert result.missing == ["apps/gone/service.py"]

    def test_a_renamed_file_is_reported(self, tmp_path: Path) -> None:
        """The likeliest way a true row goes stale — hence the unfiltered hook."""
        (tmp_path / "apps").mkdir()
        (tmp_path / "apps" / "renamed.py").touch()

        result = audit(_HEADER + _row("apps/original.py"), tmp_path)

        assert result.missing == ["apps/original.py"]


class TestRealPathsAreChecked:
    """Regressions on the suffix allowlist that made the gate weaker than a one-liner."""

    def test_an_extensionless_dotfile_counts(self, tmp_path: Path) -> None:
        (tmp_path / ".gitattributes").touch()

        result = audit(_HEADER + _row(".gitattributes"), tmp_path)

        assert result.present == [".gitattributes"]
        assert not result.not_paths

    def test_a_directory_counts(self, tmp_path: Path) -> None:
        (tmp_path / "docs" / "adr").mkdir(parents=True)

        result = audit(_HEADER + _row("docs/adr/"), tmp_path)

        assert result.present == ["docs/adr/"]

    def test_a_double_suffix_counts(self, tmp_path: Path) -> None:
        (tmp_path / "t.json.template").touch()

        result = audit(_HEADER + _row("t.json.template"), tmp_path)

        assert result.present == ["t.json.template"]

    def test_a_missing_dotfile_is_not_excused_as_a_non_path(self, tmp_path: Path) -> None:
        """Absent AND unusual-looking must still be a failure, not a skip."""
        result = audit(_HEADER + _row("frontend/.nvmrc"), tmp_path)

        assert result.missing == ["frontend/.nvmrc"]


class TestNonPaths:
    def test_a_command_is_skipped(self, tmp_path: Path) -> None:
        result = audit(_HEADER + _row("npm run gen:api"), tmp_path)

        assert result.not_paths == ["npm run gen:api"]
        assert not result.missing

    def test_a_function_reference_is_skipped_only_when_its_module_exists(
        self, tmp_path: Path
    ) -> None:
        """`apps/xero/seeding._employees_phase` is a true row; the module proves it."""
        (tmp_path / "apps" / "xero").mkdir(parents=True)
        (tmp_path / "apps" / "xero" / "seeding.py").touch()

        result = audit(_HEADER + _row("apps/xero/seeding._employees_phase"), tmp_path)

        assert result.not_paths == ["apps/xero/seeding._employees_phase"]

    def test_a_function_reference_whose_module_is_gone_is_reported(self, tmp_path: Path) -> None:
        """Deleting the module must not silently promote the row to 'not a path'."""
        result = audit(_HEADER + _row("apps/xero/seeding._employees_phase"), tmp_path)

        assert result.missing == ["apps/xero/seeding._employees_phase"]


class TestRowSelection:
    def test_rows_with_other_dispositions_are_ignored(self, tmp_path: Path) -> None:
        """Only `ported` claims existence; `dropped` deliberately names a gone file."""
        markdown = _HEADER + "| something | dropped | `apps/gone/service.py` |\n"

        result = audit(markdown, tmp_path)

        assert not result.missing
        assert not result.present

    def test_only_the_first_backticked_token_is_taken_as_the_path(self, tmp_path: Path) -> None:
        """Later backticks in the notes column are prose, not a second claim."""
        (tmp_path / "real.py").touch()
        markdown = _HEADER + "| something | ported | `real.py` | see `NotAFile` |\n"

        result = audit(markdown, tmp_path)

        assert result.present == ["real.py"]
        assert not result.missing
