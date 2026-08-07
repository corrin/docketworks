"""Repo tooling, grouped by what each script does to the repo.

- ``checks/``   gate: exits non-zero when something is wrong. CI runs these.
- ``generate/`` writes a committed artefact; CI re-runs and diffs the result.
- ``ops/``      operational tooling for cutover and diagnosis, run by hand.

``registry.py`` is the inventory: every script above appears there with its role
and tier, and a test fails if CI and the registry disagree. Adding a script
without registering it is the failure this exists to prevent.

Run them as ``uv run python -m scripts.<group>.<name>``; ``-m`` puts the working
directory on ``sys.path``, which is what makes the ``scripts.`` imports resolve.
"""

from pathlib import Path

#: The repo root, defined once. Each script used to derive this itself with
#: ``parent.parent``, which meant eight copies that were all silently wrong the
#: moment the files moved into subdirectories. Depth is this file's problem now.
REPO_ROOT = Path(__file__).resolve().parent.parent
