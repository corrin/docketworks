from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        (
            "workflow",
            "0232_rename_workflow_ap_timesta_a3d224_idx_workflow_apperror_time_sev_idx_and_more",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="companydefaults",
            name="job_delta_soft_fail",
            field=models.BooleanField(
                default=True,
                help_text="When enabled, job delta checksum mismatches are logged and recorded without blocking the save. Disable to reject stale updates.",
            ),
        ),
        migrations.AddField(
            model_name="companydefaults",
            name="phone_call_downloads_enabled",
            field=models.BooleanField(
                default=False,
                help_text="Enable scheduled phone call and recording downloads.",
            ),
        ),
        migrations.AddField(
            model_name="companydefaults",
            name="phone_own_numbers",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Normalized company-owned phone numbers used to determine inbound and outbound call direction.",
            ),
        ),
        migrations.AddField(
            model_name="companydefaults",
            name="phone_provider_account_code",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Provider account code used when fetching and deleting recordings.",
                max_length=100,
            ),
        ),
        migrations.AddField(
            model_name="companydefaults",
            name="phone_provider_base_url",
            field=models.URLField(
                blank=True,
                default="",
                help_text="Base URL for the configured phone provider portal.",
            ),
        ),
        migrations.AddField(
            model_name="companydefaults",
            name="phone_provider_password",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Password for the configured phone provider portal.",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="companydefaults",
            name="phone_provider_recording_deletion_enabled",
            field=models.BooleanField(
                default=False,
                help_text="Enable deletion of provider-side recordings after they have been archived locally and aged past the retention delay.",
            ),
        ),
        migrations.AddField(
            model_name="companydefaults",
            name="phone_provider_username",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Username for the configured phone provider portal.",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="companydefaults",
            name="xero_automated_day_floor",
            field=models.PositiveIntegerField(
                default=100,
                help_text="Reserve this many Xero daily API calls for user-initiated work. Automated sync aborts when the active Xero app reports remaining daily calls at or below this value.",
            ),
        ),
    ]
