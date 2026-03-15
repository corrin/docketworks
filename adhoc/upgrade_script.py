#!/usr/bin/env python3
"""
Upgrade script: reads pyproject.toml, fetches PyPI data for each dependency,
and prints a Markdown table with:
- package_name
- section (dependencies/dev)
- version_requested
- date_version_requested
- latest_version
- date_latest_version
- days_between
"""

import sys
from datetime import datetime

import pandas as pd
import requests
import toml


def normalize_version(spec: str) -> str:
    """Simplify a version specifier like '^1.2.3' or '>=1.0,<2.0' to its base version."""
    base = spec.split(",")[0].strip()
    for op in ("^", "~", ">=", "<=", "=", ">"):
        if base.startswith(op):
            base = base[len(op) :]
    return base


def fetch_release_dates(name: str, requested_version: str):
    url = f"https://pypi.org/pypi/{name}/json"
    resp = requests.get(url)
    data = resp.json()

    latest_ver = data["info"]["version"]
    all_dates = [
        datetime.fromisoformat(rel["upload_time"])
        for rel_list in data["releases"].values()
        for rel in rel_list
        if "upload_time" in rel
    ]
    latest_date = max(all_dates).date()

    req_releases = data["releases"].get(requested_version, [])
    if req_releases:
        req_dates = [datetime.fromisoformat(rel["upload_time"]) for rel in req_releases]
        requested_date = max(req_dates).date()
        days_between = (max(all_dates) - max(req_dates)).days
    else:
        requested_date = None
        days_between = None

    return latest_ver, latest_date, requested_date, days_between


def main(pyproject_path):
    pyproject = toml.load(pyproject_path)

    deps = pyproject.get("tool", {}).get("poetry", {}).get("dependencies", {})
    dev_deps = (
        pyproject.get("tool", {})
        .get("poetry", {})
        .get("group", {})
        .get("dev", {})
        .get("dependencies", {})
    )

    rows = []
    for section, pkg_map in [("dependencies", deps), ("dev", dev_deps)]:
        for name, spec in pkg_map.items():
            if name.lower() == "python" or not isinstance(spec, str):
                continue
            requested_version = normalize_version(spec)
            latest_ver, latest_date, req_date, days_between = fetch_release_dates(
                name, requested_version
            )
            rows.append(
                {
                    "package_name": name,
                    "section": section,
                    "version_requested": requested_version,
                    "date_version_requested": req_date,
                    "latest_version": latest_ver,
                    "date_latest_version": latest_date,
                    "days_between": days_between,
                }
            )

    df = pd.DataFrame(rows)
    df_sorted = df.sort_values(by="days_between", ascending=False).reset_index(
        drop=True
    )
    print(df_sorted.to_markdown(index=False))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python upgrade_script.py <path/to/pyproject.toml>")
        sys.exit(1)
    main(sys.argv[1])
