from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("job", "0082_drop_jobevent_description"),
    ]

    operations = [
        TrigramExtension(),
    ]
