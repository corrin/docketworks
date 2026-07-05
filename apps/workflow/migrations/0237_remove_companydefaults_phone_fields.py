from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0006_phone_endpoints_and_classification"),
        ("workflow", "0236_remove_companydefaults_charge_out_rate"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="companydefaults",
            name="company_phone",
        ),
        migrations.RemoveField(
            model_name="companydefaults",
            name="phone_call_downloads_enabled",
        ),
        migrations.RemoveField(
            model_name="companydefaults",
            name="phone_provider_recording_deletion_enabled",
        ),
        migrations.RemoveField(
            model_name="companydefaults",
            name="phone_provider_base_url",
        ),
        migrations.RemoveField(
            model_name="companydefaults",
            name="phone_provider_username",
        ),
        migrations.RemoveField(
            model_name="companydefaults",
            name="phone_provider_password",
        ),
        migrations.RemoveField(
            model_name="companydefaults",
            name="phone_provider_account_code",
        ),
        migrations.RemoveField(
            model_name="companydefaults",
            name="phone_own_numbers",
        ),
    ]
