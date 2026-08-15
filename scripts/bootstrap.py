"""Configure Django for a script, once.

Every script under ``scripts/`` that touches the ORM needs the same two
things before it can import from ``apps``: ``DJANGO_SETTINGS_MODULE`` set and
``django.setup()`` called. That was copied into 29 files, along with a
hand-counted ``parent.parent.parent`` repo-root insert that came in five
different depths — the exact breakage ``scripts/__init__.REPO_ROOT``'s
comment records having already fixed once.

No ``sys.path`` manipulation here: the package docstring mandates
``uv run python -m scripts.<group>.<name>``, and ``-m`` puts the working
directory on the path, which is what makes both ``scripts.`` and ``apps.``
resolve. Importing this module at all proves the invocation was right — a
by-path run fails on this import instead of silently running with a
different root than the one it computed.

Usage, as the first statement after the stdlib imports::

    from scripts.bootstrap import setup_django

    setup_django()

    from apps.job.models import Job  # noqa: E402 -- Django must be configured first
"""

import os


def setup_django() -> None:
    """Point Django at the project settings and initialise the app registry."""
    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()
