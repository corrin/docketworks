"""The integration pre-flight must agree with the app, not restate it.

The bash version it replaced grepped `.env` and disagreed with every rule it
restated. These pin the three disagreements, because each one is silent: the
run proceeds and the operator is told nothing.
"""

import pytest
from django.test import override_settings

from scripts.ops.assert_integration_target import main


@pytest.mark.parametrize(
    ("db_name", "expected"),
    [
        ("dw_msm_prod", 1),
        ("dw_msm_dev", 0),
        ("dw_msm_uat", 0),
        # test wins over prod: Django's runner prefixes the configured name, so
        # this is a synthetic database. The old `*_prod` glob refused it, which
        # would have blocked the one place tests may run near production
        # credentials.
        ("test_dw_msm_prod", 0),
    ],
)
def test_it_classifies_the_target_the_way_the_app_does(db_name: str, expected: int) -> None:
    with override_settings(DATABASES={"default": {"NAME": db_name}}, XERO_READONLY=False):
        assert main() == expected


def test_it_refuses_a_write_suppressed_run(capsys: pytest.CaptureFixture[str]) -> None:
    """XERO_READONLY suppresses exactly the writes these tests exist to prove.

    The bash guard matched `^XERO_READONLY=true` literally, so `TRUE` in .env
    passed it while settings lowercased the value and turned readonly ON.
    Reading the parsed setting cannot have that gap.
    """
    with override_settings(DATABASES={"default": {"NAME": "dw_msm_dev"}}, XERO_READONLY=True):
        assert main() == 1

    assert "XERO_READONLY" in capsys.readouterr().err


def test_it_reads_the_database_the_app_resolved(capsys: pytest.CaptureFixture[str]) -> None:
    """Not `.env`. settings calls load_dotenv(override=False), so an exported
    DB_NAME wins — and a .env grep could not see the database the run uses.
    """
    with override_settings(DATABASES={"default": {"NAME": "dw_msm_dev"}}, XERO_READONLY=False):
        assert main() == 0

    assert "dw_msm_dev" in capsys.readouterr().out
