"""Repo tooling: gates, schema export and parity, goldens, status.

A package rather than loose files so the modules can import each other by name.
Run them as ``uv run python -m scripts.<name>``: ``-m`` puts the working
directory on ``sys.path``, which is what makes ``from scripts.x import y``
resolve. Running one by path instead (``python scripts/x.py``) puts *scripts/*
on the path rather than the repo root, so the sibling import fails — which is
why each script used to open with its own ``sys.path.insert``.
"""
