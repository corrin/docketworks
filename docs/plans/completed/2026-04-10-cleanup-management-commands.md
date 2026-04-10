# Clean Up Unused Management Commands

## Context

The project has 32 management commands. Many are one-off debug/test scripts. This cleans up `management/commands/` — deleting dead code and moving reusable onboarding/ops tools to `scripts/`.

## DELETE — dead code, will never be run again

| Command | Reason |
|---------|--------|
| `accounts/.../adapt_migrations_accounts.py` | One-off historical migration fix |
| `job/.../test_claude_chat.py` | Superseded by test_gemini_chat |
| `job/.../test_diff_engine.py` | Hardcoded test data for a single function |
| `job/.../test_event_deduplication.py` | Should be unit tests, not a command |
| `job/.../create_test_quote_data.py` | Creates generic fake data ("Software Licenses") — not useful for real onboarding |
| `workflow/.../invoice_line.py` | Not even a Command class — orphaned utility function with no callers |
| `workflow/.../recreate_all_init_files.py` | Redundant with `scripts/update_init.py` |

## MOVE TO `scripts/` — useful for customer onboarding or ongoing ops

| Command | New location | When used |
|---------|-------------|-----------|
| `client/.../geocode_addresses.py` | `scripts/geocode_addresses.py` | Onboarding: batch geocode imported supplier addresses. Ongoing: after bulk supplier imports. (Inline geocoding in `address_views.py` only handles one-at-a-time via UI.) |
| `client/.../analyze_client_contacts.py` | `scripts/analyze_client_contacts.py` | Onboarding: check imported client data for duplicates/empty names before go-live. |
| `job/.../test_quote_import.py` | `scripts/test_quote_import.py` | Onboarding: test that the client's quote spreadsheet format imports correctly before going live. |
| `quoting/.../populate_product_mappings.py` | `scripts/populate_product_mappings.py` | Onboarding: populate product parsing mappings after importing supplier catalog. |

Each moved script needs Django bootstrap added:
```python
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")
django.setup()
```
Convert `BaseCommand.handle()` to `main()` with `argparse`.

## Also

- Run `python scripts/update_init.py` to regenerate `__init__.py` files
- Remove `# or backport_data_restore` comment from `AGENTS.md` line 30

## Verification

- `python manage.py help` — deleted commands gone
- `python manage.py check` — no import errors
- Moved scripts work: `python scripts/geocode_addresses.py --help` etc.
- Pre-commit hooks pass
