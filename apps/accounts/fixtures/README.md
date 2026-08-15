# accounts fixtures

## initial_data.json

Eleven demo staff plus the main-line phone endpoint they answer
(`accounts.staff` and `crm.phoneendpoint` rows). Ported from v1's
`apps/workflow/fixtures/initial_data.json`; the model labels were already the
v2 app labels, so the content is unchanged.

It lives in `accounts/` because staff are the fixture's subject; the one
`crm.phoneendpoint` row rides along because a fixture must load atomically
with the staff it references. JSON carries no comments, hence this file.

Loaded by `scripts/server/instance.sh --seed` when provisioning a demo
instance (that wiring lands separately); load by hand with:

    uv run python manage.py loaddata initial_data

Every staff row shares one known password hash (the standard demo login) and
`xero_user_id: null` — `finalize_instance_onboarding --seed-xero` links them
to the demo tenant later.
