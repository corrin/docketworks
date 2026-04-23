# DB-level enforcement of the CompanyDefaults singleton.
#
# django-solo forces pk=1 in SingletonModel.save(), but nothing at the schema
# level stops a caller (raw SQL, bulk_create, a fixture, loaddata) from
# creating a second row. Combined with the existing PRIMARY KEY on id, this
# check constraint makes "exactly one row with id=1" a hard invariant:
# any attempt to insert id != 1 fails the check, and any second row with id=1
# fails the PK.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0211_apperror_app_error_resolved_msg_idx"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="companydefaults",
            constraint=models.CheckConstraint(
                condition=models.Q(id=1),
                name="companydefaults_singleton",
            ),
        ),
    ]
