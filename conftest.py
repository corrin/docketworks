"""Pytest session setup.

Test DB and test role are pre-provisioned by scripts/server/instance.sh.
The test role owns the test DB but has no CREATEDB — so we cannot let
pytest-django's default setup_databases run (it would try CREATE DATABASE).

Instead, swap the connection name to the test DB, drop and recreate the
public schema (the test role can do this because it owns the DB), and run
migrations from scratch each session.
"""

import pytest


@pytest.fixture(scope="session")
def django_db_setup(django_db_blocker):
    from django.core.management import call_command
    from django.db import connection

    with django_db_blocker.unblock():
        original_name = connection.settings_dict["NAME"]
        connection.settings_dict["NAME"] = f"test_{original_name}"
        connection.close()

        with connection.cursor() as cursor:
            cursor.execute("DROP SCHEMA public CASCADE")
            cursor.execute("CREATE SCHEMA public")
        call_command("migrate", "--no-input")
