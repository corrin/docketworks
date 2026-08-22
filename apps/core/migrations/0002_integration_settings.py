"""IntegrationSettings adopts the phone-provider table and gains the Maps key.

The state operation describes the table as crm/0001 created it, so the schema
editor sees no difference; the renames and the new column are the only
physical changes. ``db_table`` stays ``crm_phoneprovidersettings`` because v1's
dump restores by table name (ADR 0053; docs/rewrite-status.md carries the
post-cutover rename).
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
        ("crm", "0002_phone_provider_settings_moves_to_core"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="IntegrationSettings",
                    fields=[
                        (
                            "id",
                            models.PositiveSmallIntegerField(
                                default=1, editable=False, primary_key=True, serialize=False
                            ),
                        ),
                        ("downloads_enabled", models.BooleanField(default=False)),
                        ("recording_deletion_enabled", models.BooleanField(default=False)),
                        ("base_url", models.URLField(blank=True, default=None, null=True)),
                        ("username", models.TextField(blank=True, null=True)),
                        ("password", models.TextField(blank=True, null=True)),
                        (
                            "account_code",
                            models.CharField(blank=True, max_length=100, null=True),
                        ),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                    ],
                    options={
                        "db_table": "crm_phoneprovidersettings",
                        "verbose_name": "Integration Settings",
                        "verbose_name_plural": "Integration Settings",
                        "constraints": [
                            models.CheckConstraint(
                                condition=models.Q(("account_code", ""), _negated=True),
                                name="crm_phoneprovidersettings_account_code_not_blank",
                            ),
                            models.CheckConstraint(
                                condition=models.Q(("base_url", ""), _negated=True),
                                name="base_url_not_blank",
                            ),
                            models.CheckConstraint(
                                condition=models.Q(("password", ""), _negated=True),
                                name="crm_phoneprovidersettings_password_not_blank",
                            ),
                            models.CheckConstraint(
                                condition=models.Q(("username", ""), _negated=True),
                                name="crm_phoneprovidersettings_username_not_blank",
                            ),
                        ],
                    },
                ),
            ],
            database_operations=[],
        ),
        migrations.RemoveConstraint(
            model_name="integrationsettings",
            name="crm_phoneprovidersettings_account_code_not_blank",
        ),
        migrations.RemoveConstraint(model_name="integrationsettings", name="base_url_not_blank"),
        migrations.RemoveConstraint(
            model_name="integrationsettings",
            name="crm_phoneprovidersettings_password_not_blank",
        ),
        migrations.RemoveConstraint(
            model_name="integrationsettings",
            name="crm_phoneprovidersettings_username_not_blank",
        ),
        migrations.RenameField(
            model_name="integrationsettings",
            old_name="downloads_enabled",
            new_name="phone_provider_downloads_enabled",
        ),
        migrations.RenameField(
            model_name="integrationsettings",
            old_name="recording_deletion_enabled",
            new_name="phone_provider_recording_deletion_enabled",
        ),
        migrations.RenameField(
            model_name="integrationsettings",
            old_name="base_url",
            new_name="phone_provider_base_url",
        ),
        migrations.RenameField(
            model_name="integrationsettings",
            old_name="username",
            new_name="phone_provider_username",
        ),
        migrations.RenameField(
            model_name="integrationsettings",
            old_name="password",
            new_name="phone_provider_password",
        ),
        migrations.RenameField(
            model_name="integrationsettings",
            old_name="account_code",
            new_name="phone_provider_account_code",
        ),
        migrations.AddField(
            model_name="integrationsettings",
            name="google_maps_api_key",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddConstraint(
            model_name="integrationsettings",
            constraint=models.CheckConstraint(
                condition=models.Q(("id", 1)), name="core_integrationsettings_singleton"
            ),
        ),
        migrations.AddConstraint(
            model_name="integrationsettings",
            constraint=models.CheckConstraint(
                condition=models.Q(("google_maps_api_key", ""), _negated=True),
                name="core_integrationsettings_google_maps_api_key_not_blank",
            ),
        ),
        migrations.AddConstraint(
            model_name="integrationsettings",
            constraint=models.CheckConstraint(
                condition=models.Q(("phone_provider_base_url", ""), _negated=True),
                name="core_integrationsettings_phone_provider_base_url_not_blank",
            ),
        ),
        migrations.AddConstraint(
            model_name="integrationsettings",
            constraint=models.CheckConstraint(
                condition=models.Q(("phone_provider_username", ""), _negated=True),
                name="core_integrationsettings_phone_provider_username_not_blank",
            ),
        ),
        migrations.AddConstraint(
            model_name="integrationsettings",
            constraint=models.CheckConstraint(
                condition=models.Q(("phone_provider_password", ""), _negated=True),
                name="core_integrationsettings_phone_provider_password_not_blank",
            ),
        ),
        migrations.AddConstraint(
            model_name="integrationsettings",
            constraint=models.CheckConstraint(
                condition=models.Q(("phone_provider_account_code", ""), _negated=True),
                name="core_integrationsettings_phone_provider_account_code_not_blank",
            ),
        ),
    ]
