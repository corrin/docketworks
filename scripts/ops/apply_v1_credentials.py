"""One-off, cutover phase 3: load extracted v1 credentials into v2.

Fable: the second half of the pair — runs after ``migrate_v1_data.sh`` and
BEFORE ``instance.sh load-db-fixtures``, so the loader then sees a configured
phone group and honours it ("applies only while columns are unset") instead
of overwriting operator-entered secrets. Reads the file
``extract_v1_credentials.py`` wrote while v1 was intact; the migration's own
clearing step is the fallback for restores that never extracted (scrubbed
dumps carry no real secrets).

Runs through Django (``manage.py shell``-style, via the release venv and the
v2 ``.env``), so it writes the renamed v2 columns and re-uses model save.
Keyed by the supplier credential's pk, which migrated byte-identical.

Usage (as the instance user, in the release dir):
  DJANGO_SETTINGS_MODULE=config.settings python scripts/ops/apply_v1_credentials.py <file.json>

Deletable with scripts/server/cutover/ once both hosts run v2.
"""

import json
import sys
from pathlib import Path

import django


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage: apply_v1_credentials.py <extracted-credentials.json>")
    payload = json.loads(Path(sys.argv[1]).read_text())

    django.setup()
    from django.db import transaction

    from apps.core.models import IntegrationSettings
    from apps.quoting.models import SupplierCredential

    phone = payload.get("phone")
    suppliers = payload.get("suppliers", [])

    with transaction.atomic():
        if phone is not None:
            settings_row = IntegrationSettings.get_solo()
            settings_row.phone_provider_enabled = phone["enabled"]
            settings_row.phone_provider_recording_deletion_enabled = phone[
                "recording_deletion_enabled"
            ]
            settings_row.phone_provider_base_url = phone["base_url"]
            settings_row.phone_provider_username = phone["username"]
            settings_row.phone_provider_password = phone["password"]
            settings_row.phone_provider_account_code = phone["account_code"]
            settings_row.save()

        applied = 0
        missing = []
        for entry in suppliers:
            credential = SupplierCredential.objects.filter(id=entry["id"]).first()
            if credential is None:
                # The migration carries every row, so an id present at extract
                # and absent now is a real inconsistency worth surfacing, not
                # swallowing.
                missing.append(entry["id"])
                continue
            credential.username = entry["username"]
            credential.password = entry["password"]
            credential.api_key = entry["api_key"]
            credential.save()
            applied += 1

    if missing:
        sys.exit(
            f"ERROR: {len(missing)} supplier credential id(s) from the extract are "
            f"not in the migrated database: {missing}. The migration and the extract "
            "disagree — investigate before trusting the load."
        )
    print(f"Applied: phone={'yes' if phone else 'none'}, suppliers={applied}.")


if __name__ == "__main__":
    main()
