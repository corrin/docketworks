"""Category assignment from v1 tags, factored out of 0003 so it can be tested.

Frozen: edits here rewrite history. Most-specific-first; the fallbacks mirror
what the v1 category dicts meant, minus the overlap (a doc listed once, not
twice).

Fable: named ``_0003_helpers`` (leading underscore), matching
``apps/quoting/migrations/_0002_helpers.py`` and
``apps/crm/migrations/_0003_helpers.py`` — Django's migration loader treats
every non-underscore-prefixed module under ``migrations/`` as a migration and
demands a ``Migration`` class, so an un-prefixed name here breaks
``manage.py migrate`` for the whole app.

``apps/process/tests/test_backfill_categories.py`` and
``apps/process/tests/test_import_dropbox_hs_documents.py`` are the test net.
"""


def form_category(document_type: str, tags: list[str]) -> str:
    if "incident" in tags:
        return "incident"
    if document_type == "register":
        return "register"
    if "meeting" in tags:
        return "meeting"
    if "training" in tags:
        return "training"
    return "safety"


def procedure_category(document_type: str, tags: list[str]) -> str:
    if "jsa" in tags:
        return "jsa"
    if document_type == "reference":
        return "reference"
    if "training" in tags:
        return "training"
    return "safety"
