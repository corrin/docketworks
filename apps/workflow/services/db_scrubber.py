"""
Scrubs a restored copy of prod (in the `scrub` DB alias) of all PII.

Reproduces three behaviours from the legacy backport_data_backup command:
  1. Anonymise the columns in PII_CONFIG (+ _anonymize_staff).
  2. Delete the unlinked accounting records that _filter_unlinked_accounting_records dropped.
  3. Truncate the tables in EXCLUDE_MODELS (minus framework tables).

Anything beyond that is OUT OF SCOPE for this task and must NOT be added without
a separate ticket — see docs/plans/2026-04-25-pg-dump-backport-refresh-plan.md
"Strict like-for-like contract".

Safety: refuses to run unless settings.DATABASES["scrub"]["NAME"] ends in
"_scrub" — last line of defence against a misconfigured SCRUB_DB_NAME pointing
at prod.
"""

from django.conf import settings
from django.db import transaction

from apps.accounts.models import Staff
from apps.accounts.staff_anonymization import create_staff_profile
from apps.workflow.services.error_persistence import persist_app_error

SCRUB_ALIAS = "scrub"
_GENERATE_ATTEMPTS = 100


def _assert_scrub_alias_is_safe() -> None:
    name = settings.DATABASES[SCRUB_ALIAS]["NAME"]
    if not name or not name.endswith("_scrub"):
        raise RuntimeError(
            f"SCRUB_DB_NAME ({name!r}) must end in '_scrub'. "
            "Refusing to run scrubber against anything else."
        )


def _scrub_staff() -> None:
    """Mirror legacy _anonymize_staff: coherent profiles, unique emails.

    Touches first_name, last_name, preferred_name, email only — matches the
    legacy behaviour. xero_user_id and password are intentionally left alone.
    """
    used_emails: set[str] = set()
    for staff in Staff.objects.using(SCRUB_ALIAS).all():
        for _ in range(_GENERATE_ATTEMPTS):
            profile = create_staff_profile()
            if profile["email"] not in used_emails:
                break
        else:
            raise RuntimeError(
                f"Could not generate unique staff email after "
                f"{_GENERATE_ATTEMPTS} attempts; {len(used_emails)} in use."
            )
        used_emails.add(profile["email"])
        staff.email = profile["email"]
        staff.first_name = profile["first_name"]
        staff.last_name = profile["last_name"]
        staff.preferred_name = profile["preferred_name"]
        staff.save(
            using=SCRUB_ALIAS,
            update_fields=["email", "first_name", "last_name", "preferred_name"],
        )


def scrub() -> None:
    """Reproduce the legacy command's PII handling on the scrub DB.

    Single transaction. Persists and re-raises on any error.
    """
    _assert_scrub_alias_is_safe()
    try:
        with transaction.atomic(using=SCRUB_ALIAS):
            # Per-step helpers added by subsequent tasks.
            _scrub_staff()
    except Exception as exc:
        persist_app_error(exc)
        raise
