from django.db import migrations


class Migration(migrations.Migration):
    """Rename the send timestamp to name the state it actually records.

    Agreement between the two copies is reached either by sending ours or by
    taking Xero's, so a column called "last pushed" could only be written by
    one of the two paths — and the other then looked like an unsent local
    edit forever. The field is unreleased (added earlier in this same branch),
    so this renames rather than deprecates.
    """

    dependencies = [("purchasing", "0003_purchaseorder_xero_last_pushed")]

    operations = [
        migrations.RenameField(
            model_name="purchaseorder",
            old_name="xero_last_pushed",
            new_name="xero_agreed_at",
        ),
    ]
