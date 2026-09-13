"""Adopting integration settings must preserve data and permission identities."""

from collections.abc import Iterator

import pytest
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.state import StateApps

from apps.accounts.models import Staff

OLD = ("core", "0007_retention_and_quote_expiry_settings")
NEW = ("integrations", "0002_transfer_content_type")

# GPT: PostgreSQL rolls back this DDL with each test. TransactionTestCase's
# flush teardown is deliberately forbidden by ADR 0048.
pytestmark = pytest.mark.django_db


def _migrate(target: tuple[str, str]) -> StateApps:
    # GPT: production commits fixture writes before migration DDL. This test
    # keeps rollback isolation, so validate deferred FKs explicitly before
    # ALTER TABLE rather than leaving their trigger events pending.
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    executor = MigrationExecutor(connection)
    executor.migrate([target])
    return executor.loader.project_state([target]).apps


@pytest.fixture
def legacy_state() -> Iterator[StateApps]:
    state = _migrate(OLD)
    try:
        yield state
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())


def test_upgrade_preserves_every_column_and_the_physical_table(legacy_state: StateApps) -> None:
    legacy = legacy_state.get_model("core", "IntegrationSettings")
    legacy.objects.update_or_create(
        pk=1,
        defaults={
            "google_maps_api_key": "migration-test-maps",
            "phone_provider_enabled": True,
            "phone_provider_recording_deletion_enabled": True,
            "phone_provider_recording_deletion_after_days": 47,
            "phone_provider_base_url": "https://phone.example.test",
            "phone_provider_username": "migration-user",
            "phone_provider_password": "migration-secret",
            "phone_provider_account_code": "migration-account",
        },
    )
    before = legacy.objects.values().get(pk=1)
    with connection.cursor() as cursor:
        cursor.execute("SELECT 'crm_phoneprovidersettings'::regclass::oid")
        table_identity = cursor.fetchone()
        constraints = connection.introspection.get_constraints(cursor, legacy._meta.db_table)

    state = _migrate(NEW)
    adopted = state.get_model("integrations", "IntegrationSettings")

    assert adopted.objects.values().get(pk=1) == before
    with connection.cursor() as cursor:
        cursor.execute("SELECT 'crm_phoneprovidersettings'::regclass::oid")
        assert cursor.fetchone() == table_identity
        assert (
            connection.introspection.get_constraints(cursor, adopted._meta.db_table) == constraints
        )
    with pytest.raises(LookupError):
        state.get_model("core", "IntegrationSettings")


@pytest.mark.usefixtures("legacy_state")
def test_upgrade_preserves_content_type_permissions_and_grants(superuser: Staff) -> None:
    content_type, _ = ContentType.objects.get_or_create(
        app_label="core", model="integrationsettings"
    )
    permission, _ = Permission.objects.get_or_create(
        content_type=content_type,
        codename="change_integrationsettings",
        defaults={"name": "Can change integration settings"},
    )
    group = Group.objects.create(name="Integration operators")
    group.permissions.add(permission)
    superuser.user_permissions.add(permission)
    identity = content_type.pk

    _migrate(NEW)

    assert (
        ContentType.objects.get(app_label="integrations", model="integrationsettings").pk
        == identity
    )
    assert not ContentType.objects.filter(app_label="core", model="integrationsettings").exists()
    permission.refresh_from_db()
    assert permission.content_type_id == identity
    assert group.permissions.get().pk == permission.pk
    assert superuser.user_permissions.get().pk == permission.pk


def test_fresh_install_without_a_content_type_keeps_the_seeded_row(legacy_state: StateApps) -> None:
    ContentType.objects.filter(model="integrationsettings").delete()
    # GPT: replay the historical seed exactly as a fresh install/cutover does;
    # the adopting migration must not depend on post_migrate having run first.
    _migrate(("core", "0002_integration_settings"))
    legacy_state.get_model("core", "IntegrationSettings").objects.all().delete()

    state = _migrate(NEW)

    assert state.get_model("integrations", "IntegrationSettings").objects.filter(pk=1).exists()
    assert not ContentType.objects.filter(model="integrationsettings").exists()


@pytest.mark.usefixtures("legacy_state")
def test_ambiguous_content_types_abort_without_discarding_permissions() -> None:
    original, _ = ContentType.objects.get_or_create(app_label="core", model="integrationsettings")
    conflict = ContentType.objects.create(app_label="integrations", model="integrationsettings")
    try:
        with pytest.raises(RuntimeError, match="Both core and integrations ContentTypes"):
            _migrate(NEW)
        assert ContentType.objects.filter(pk__in=[original.pk, conflict.pk]).count() == 2
    finally:
        conflict.delete()


def test_restore_rewind_and_reapply_preserve_the_singleton(legacy_state: StateApps) -> None:
    legacy = legacy_state.get_model("core", "IntegrationSettings")
    legacy.objects.update_or_create(pk=1, defaults={"phone_provider_enabled": False})
    _migrate(NEW)

    _migrate(("core", "0001_initial"))
    with connection.cursor() as cursor:
        cursor.execute("SELECT downloads_enabled FROM crm_phoneprovidersettings WHERE id = 1")
        assert cursor.fetchone() == (False,)

    adopted_state = _migrate(NEW)
    assert (
        adopted_state.get_model("integrations", "IntegrationSettings").objects.filter(pk=1).exists()
    )
