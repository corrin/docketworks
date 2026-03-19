#!/usr/bin/env python3
"""
Find late imports in Python files.

This script identifies imports that appear inside functions rather than at module level.
It can filter for "easy" stdlib imports that should definitely be at the top,
or show all late imports.

Files that contain comments with "circular import" or "AppRegistryNotReady" are
automatically excluded, as these indicate intentional late imports.

Usage:
    python scripts/find_late_imports.py           # Show easy stdlib late imports
    python scripts/find_late_imports.py --all     # Show all late imports
"""

import argparse
import ast
import os
import re
import sys

# Standard library imports that should always be at module level
EASY_STDLIB_IMPORTS = [
    "import os",
    "import logging",
    "import json",
    "import time",
    "import datetime",
    "import tempfile",
    "import uuid",
    "import signal",
    "import sys",
    "import traceback",
    "import threading",
    "import tracemalloc",
    "from datetime",
    "from uuid",
    "from collections",
    "from pprint",
]

# Internal app imports that should be at module level (not circular import workarounds)
EASY_APP_IMPORTS = [
    "from apps.workflow.exceptions",
]

# Patterns in comments that indicate intentional late imports
LATE_IMPORT_EXCUSE_PATTERNS = [
    r"circular\s+import",
    r"AppRegistryNotReady",
    r"avoid.*import.*error",
    r"Django\s+startup",
]


class ImportVisitor(ast.NodeVisitor):
    def __init__(self, filepath: str, easy_only: bool = True):
        self.filepath = filepath
        self.issues: list[tuple[int, str]] = []
        self.in_function = False
        self.easy_only = easy_only

    def visit_FunctionDef(self, node):
        old = self.in_function
        self.in_function = True
        self.generic_visit(node)
        self.in_function = old

    def visit_AsyncFunctionDef(self, node):
        old = self.in_function
        self.in_function = True
        self.generic_visit(node)
        self.in_function = old

    def _is_easy_import(self, import_str: str) -> bool:
        """Check if import matches easy patterns (stdlib or app imports)."""
        for easy in EASY_STDLIB_IMPORTS + EASY_APP_IMPORTS:
            if import_str.startswith(easy):
                return True
        return False

    def visit_Import(self, node):
        if self.in_function:
            names = ", ".join(a.name for a in node.names)
            import_str = f"import {names}"
            if self.easy_only:
                if self._is_easy_import(import_str):
                    self.issues.append((node.lineno, import_str))
            else:
                self.issues.append((node.lineno, import_str))

    def visit_ImportFrom(self, node):
        if self.in_function:
            mod = node.module or "."
            import_str = f"from {mod}"
            if self.easy_only:
                if self._is_easy_import(import_str):
                    self.issues.append((node.lineno, import_str))
            else:
                self.issues.append((node.lineno, import_str))


def has_late_import_excuse(content: str) -> bool:
    """Check if file contains comments explaining why late imports are needed."""
    for pattern in LATE_IMPORT_EXCUSE_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return True
    return False


def find_late_imports(
    root_dirs: list[str],
    easy_only: bool = True,
    skip_tests: bool = True,
    skip_migrations: bool = True,
    skip_excused: bool = True,
) -> list[tuple[str, int, str]]:
    """Find late imports in Python files."""
    results = []

    for root_dir in root_dirs:
        for dirpath, dirnames, filenames in os.walk(root_dir):
            # Skip directories
            if skip_migrations and "migrations" in dirpath:
                continue
            if skip_tests and "/tests" in dirpath:
                continue

            for filename in filenames:
                if filename.endswith(".py") and filename != "__init__.py":
                    filepath = os.path.join(dirpath, filename)
                    try:
                        with open(filepath, "r") as f:
                            content = f.read()

                        # Skip files that explain why late imports are needed
                        if skip_excused and has_late_import_excuse(content):
                            continue

                        tree = ast.parse(content)
                        visitor = ImportVisitor(filepath, easy_only=easy_only)
                        visitor.visit(tree)
                        for lineno, name in visitor.issues:
                            results.append((filepath, lineno, name))
                    except SyntaxError:
                        print(f"Syntax error in {filepath}", file=sys.stderr)
                    except Exception as e:
                        print(f"Error processing {filepath}: {e}", file=sys.stderr)

    return results


def main():
    parser = argparse.ArgumentParser(description="Find late imports in Python files")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Show all late imports, not just easy stdlib ones",
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Include test files",
    )
    parser.add_argument(
        "--include-excused",
        action="store_true",
        help="Include files that have comments explaining late imports (circular import, etc.)",
    )
    parser.add_argument(
        "dirs",
        nargs="*",
        default=["apps", "jobs_manager"],
        help="Directories to scan (default: apps jobs_manager)",
    )
    args = parser.parse_args()

    results = find_late_imports(
        args.dirs,
        easy_only=not args.all,
        skip_tests=not args.include_tests,
        skip_excused=not args.include_excused,
    )

    for filepath, lineno, name in sorted(results):
        print(f"{filepath}:{lineno}: {name}")

    print(f"\nTotal: {len(results)} late imports found", file=sys.stderr)


if __name__ == "__main__":
    main()
