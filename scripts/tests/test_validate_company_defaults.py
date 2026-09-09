"""Attack the company-defaults gate: prove it accepts what prepare-config produces.

Opus: this rule gates every instance creation and had never been asserted, because
it lived in a ``python3 -c`` heredoc behind a root-owned-directory check. It came
to refuse the prospect template it ships alongside — a new instance could not be
created at all — and nothing turned red. So the first case here is the one that
was missing: both shipped templates must satisfy the gate they are prepared for.

The validator is driven by subprocess rather than imported, because that is how
``instance.sh`` invokes it: as a path, under the host interpreter, with no package
context.
"""

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "server" / "validate_company_defaults.py"
TEMPLATE_DIR = REPO_ROOT / "scripts" / "server" / "templates"
SHIPPED_TEMPLATES = ("company-defaults.json.template", "company-defaults-prospect.json.template")


def _validate(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv: this interpreter, the shipped validator, a tmp_path
        [sys.executable, str(VALIDATOR), str(path)],
        capture_output=True,
        text=True,
        check=False,
    )


def _prepared(template_name: str, tmp_path: Path) -> Path:
    """Render a shipped template the way an operator completing it would.

    Substitutes every ``__TOKEN__`` with a plausible value, because the gate
    refuses a file that still carries one and that is not what is under test here.
    """
    text = (TEMPLATE_DIR / template_name).read_text()
    written = tmp_path / template_name.replace(".template", "")
    written.write_text(re.sub(r"__[A-Z0-9_]+__", "Sample", text))
    return written


def _written(defaults: dict[str, Any], tmp_path: Path) -> Path:
    """Write a minimal two-record fixture whose CompanyDefaults fields are given."""
    records = [
        {"model": "company.company", "pk": 1, "fields": {"name": "Sample Shop"}},
        {"model": "core.companydefaults", "pk": 1, "fields": defaults},
    ]
    path = tmp_path / "company-defaults.json"
    path.write_text(json.dumps(records))
    return path


def _valid_defaults(**overrides: Any) -> dict[str, Any]:
    return {"xero_tenant_id": None, "enable_xero_sync": False, **overrides}


class TestShippedTemplates:
    @pytest.mark.parametrize("template_name", SHIPPED_TEMPLATES)
    def test_a_completed_template_satisfies_the_create_it_is_prepared_for(
        self, template_name: str, tmp_path: Path
    ) -> None:
        """The regression: prepare-config's output must pass instance.sh create.

        The prospect template shipped ``xero_tenant_id: null`` and create refused
        it, so a new instance could not be created without inventing a UUID.
        """
        result = _validate(_prepared(template_name, tmp_path))

        assert result.returncode == 0, result.stderr

    @pytest.mark.parametrize("template_name", SHIPPED_TEMPLATES)
    def test_no_shipped_template_carries_a_fabricated_tenant_id(self, template_name: str) -> None:
        """A template is a starting point, not a place to park a fake organisation."""
        records = json.loads((TEMPLATE_DIR / template_name).read_text())
        defaults = next(r["fields"] for r in records if r["model"] == "core.companydefaults")

        assert defaults["xero_tenant_id"] is None


class TestTenantId:
    def test_null_is_accepted(self, tmp_path: Path) -> None:
        """The state of every instance created before its organisation is connected."""
        assert _validate(_written(_valid_defaults(), tmp_path)).returncode == 0

    def test_a_real_uuid_is_accepted(self, tmp_path: Path) -> None:
        """An operator who already knows the organisation's id may supply it."""
        defaults = _valid_defaults(xero_tenant_id="75e57cfd-302d-4f84-8734-8aae354e76a7")

        assert _validate(_written(defaults, tmp_path)).returncode == 0

    def test_the_all_zero_placeholder_is_refused(self, tmp_path: Path) -> None:
        """Xero never issues it, so storing it sends a fabricated id in every header."""
        defaults = _valid_defaults(xero_tenant_id="00000000-0000-0000-0000-000000000000")

        result = _validate(_written(defaults, tmp_path))

        assert result.returncode != 0
        assert "all-zero placeholder" in result.stderr

    def test_a_malformed_value_is_refused(self, tmp_path: Path) -> None:
        """A value that is present must actually identify an organisation."""
        result = _validate(_written(_valid_defaults(xero_tenant_id="not-a-uuid"), tmp_path))

        assert result.returncode != 0
        assert "invalid core.companydefaults.xero_tenant_id" in result.stderr

    def test_an_empty_string_is_refused(self, tmp_path: Path) -> None:
        """Unset is NULL (ADR 0040); the database CHECK refuses "" downstream anyway."""
        result = _validate(_written(_valid_defaults(xero_tenant_id=""), tmp_path))

        assert result.returncode != 0
        assert "must be null" in result.stderr

    def test_an_absent_key_is_refused(self, tmp_path: Path) -> None:
        """Omission is not a decision: loaddata would leave the column at its default."""
        result = _validate(_written({"enable_xero_sync": False}, tmp_path))

        assert result.returncode != 0
        assert "omits core.companydefaults.xero_tenant_id" in result.stderr


class TestSyncGate:
    def test_an_open_gate_is_refused(self, tmp_path: Path) -> None:
        """Sync must not start before onboarding has bound the organisation."""
        result = _validate(_written(_valid_defaults(enable_xero_sync=True), tmp_path))

        assert result.returncode != 0
        assert "enable_xero_sync false" in result.stderr

    def test_an_absent_gate_is_refused(self, tmp_path: Path) -> None:
        """The model default is True, so an absent key is an OPEN gate, not a closed one."""
        result = _validate(_written({"xero_tenant_id": None}, tmp_path))

        assert result.returncode != 0
        assert "enable_xero_sync false" in result.stderr


class TestFileShape:
    def test_a_leftover_placeholder_is_refused(self, tmp_path: Path) -> None:
        """An uncompleted template must not reach loaddata as the client's identity."""
        result = _validate(_written(_valid_defaults(company_name="__COMPANY_NAME__"), tmp_path))

        assert result.returncode != 0
        assert "__PLACEHOLDER__" in result.stderr

    def test_a_missing_company_record_is_refused(self, tmp_path: Path) -> None:
        """CompanyDefaults points at the shop Company; one without the other is broken."""
        path = tmp_path / "company-defaults.json"
        path.write_text(
            json.dumps([{"model": "core.companydefaults", "pk": 1, "fields": _valid_defaults()}])
        )

        result = _validate(path)

        assert result.returncode != 0
        assert "exactly one Company and one CompanyDefaults" in result.stderr

    def test_an_extra_record_is_refused(self, tmp_path: Path) -> None:
        """This file is the tenant bootstrap, not a general-purpose fixture."""
        records = [
            {"model": "company.company", "pk": 1, "fields": {"name": "Sample Shop"}},
            {"model": "core.companydefaults", "pk": 1, "fields": _valid_defaults()},
            {"model": "accounts.staff", "pk": 1, "fields": {}},
        ]
        path = tmp_path / "company-defaults.json"
        path.write_text(json.dumps(records))

        result = _validate(path)

        assert result.returncode != 0
        assert "exactly one Company and one CompanyDefaults" in result.stderr
