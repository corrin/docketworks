#!/usr/bin/env python
"""Check that company defaults are loaded correctly."""

from scripts.bootstrap import setup_django

setup_django()

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
