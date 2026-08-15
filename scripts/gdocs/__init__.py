"""Google Docs/Drive authoring toolchain for the Operations Manual.

These scripts author the Google-Doc-backed documents that ``apps.process``
``Procedure`` records link to (``google_doc_id`` / ``google_doc_url``), plus
the Google Sheets quote template referenced by ``CompanyDefaults``. Run by
hand, never in CI::

    uv run python -m scripts.gdocs.explore_google_drive   # list Shared Drives / walk a tree
    uv run python -m scripts.gdocs.read_google_doc        # doc -> Markdown
    uv run python -m scripts.gdocs.write_google_doc       # Markdown -> doc (safety-netted)
    uv run python -m scripts.gdocs.set_doc_screenshot     # fill a {{screenshot:<id>}} marker
    uv run python -m scripts.gdocs.get_gapi_token         # mint an access token for manual calls
    uv run python -m scripts.gdocs.create_master_template # upload the quote template sheet

The capture half of the screenshot pipeline is
``frontend/scripts/capture-screenshots.ts`` (``npm run manual:screenshots``).
Shared service-account auth lives in ``gauth.py``.
"""
