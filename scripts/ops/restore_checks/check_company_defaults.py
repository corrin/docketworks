#!/usr/bin/env python
"""Check that company defaults are loaded correctly."""

import os
import sys
from pathlib import Path

# scripts/ops/restore_checks/ is three levels below the repo root; see
# scripts/ops/setup_dev_logins.py for why this is inserted explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from apps.core.models import CompanyDefaults  # noqa: E402 -- Django must be configured first


def main() -> None:
    defaults = CompanyDefaults.get_solo()
    print(f"Company defaults loaded: {defaults.company_name}")

    if not defaults.logo_wide:
        raise SystemExit(
            "logo_wide is empty — reload the instance's "
            ".fixtures/company_defaults.json (see scripts/server/instance.sh)."
        )
    print(f"logo_wide: {defaults.logo_wide.name}")


if __name__ == "__main__":
    main()
