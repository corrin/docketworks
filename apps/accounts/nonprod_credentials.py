"""The logins a non-production installation is given.

Public by design: these are the credentials a restored dev/UAT database hands
out, so they are documented in the restore runbook and are useless anywhere
else. They live here rather than in the scrubber or in
``scripts/ops/setup_dev_logins.py`` because both write them — the production
scrub replaces every real hash with the staff password below, and the dev
login script installs the same value plus the default admin. Two copies of a
password constant is one copy too many.
"""

ADMIN_EMAIL = "defaultadmin@example.com"
ADMIN_PASSWORD = "Default-admin-password"  # noqa: S105 -- known nonprod default, not a live secret
STAFF_PASSWORD = "Default-staff-password"  # noqa: S105 -- known nonprod default, not a live secret
