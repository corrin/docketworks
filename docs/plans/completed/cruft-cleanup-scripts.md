# Cruft Cleanup — scripts/ directory

  For each item, investigate how it's actually used in practice, fix any issues you find (missing .gitignore, missing .example, stale docs, duplicated instructions), and make everything consistent before moving on. Don't just  
  decide keep/delete.
  
## Delete

- [x] `explore_google_drive.py` — Fixed to use GCP_CREDENTIALS env var instead of hardcoded placeholder
- [x] `create_master_template.py` — Fixed to use GCP_CREDENTIALS env var instead of hardcoded path
- [x] `create_password.py` — Deleted. No __main__, no callers, trivial one-liner via django-admin shell
- [x] `get_gapi_token.py` — Fixed to use GCP_CREDENTIALS env var instead of hardcoded placeholder
- [x] `detect_fstrings_without_placeholder.py` — Not cruft. Active pre-commit hook in .pre-commit-config.yaml
- [x] `find_duplicates.py` — Not cruft. Active pre-commit hook in .pre-commit-config.yaml
- [x] `find_late_imports.py` — Fixed typo, added to pre-commit hooks. Passes clean.
- [x] `find_wrapper_candidates.py` — Kept as manual utility. Documented in scripts/README.md
- [x] `audit_view_documentation.py` — Deleted. Audits against docs/views/ which doesn't exist
- [x] `test_cross_domain_cookies.js` — Deleted. Duplicate of Python version, required extra Puppeteer dependency
- [x] `anonymize_staff.py` — Deleted. Superseded by backport_data_backup. Cleaned stale reference in staff_anonymization.py
- [x] `import_supplier_products_one_off.py` — Moved to adhoc/
