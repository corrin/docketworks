import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("company", "0001_baseline"),
        # Every app below has a baseline migration with a lazy FK reference
        # to "company.client" (the pre-rename model name). RenameModel only
        # repoints references already present in the in-memory state at the
        # moment it runs; without these edges the topological sort is free to
        # schedule this migration before those apps' baselines are replayed,
        # leaving their FKs pointing at a model name that no longer resolves.
        ("accounting", "0002_baseline"),
        ("crm", "0001_baseline"),
        ("job", "0001_baseline"),
        ("purchasing", "0001_baseline"),
        ("quoting", "0001_baseline"),
        ("workflow", "0001_baseline"),
    ]

    operations = [
        # RenameModel repoints FK/M2M references to the renamed model but does
        # not rewrite the `bases` tuple of proxy models that inherit from it
        # (Supplier(Client) -> would still record bases=("company.client",)
        # after the rename, which no longer resolves). Worse, the contenttypes
        # app injects a RenameContentType operation IMMEDIATELY after every
        # RenameModel at migrate time, and that operation renders the full
        # project state right there. So the proxy must be gone from state
        # BEFORE the rename and recreated on the new base AFTER it. A proxy
        # has no physical table (allow_migrate_model is False), so the
        # Delete+Create pair is a state-only no-op against the database.
        migrations.DeleteModel(name="Supplier"),
        migrations.RenameModel(old_name="Client", new_name="Company"),
        migrations.CreateModel(
            name="Supplier",
            fields=[],
            options={
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("company.company",),
        ),
        migrations.RenameIndex(
            model_name="company",
            old_name="client_name_fts_idx",
            new_name="company_name_fts_idx",
        ),
        migrations.RenameIndex(
            model_name="company",
            old_name="client_name_trgm_idx",
            new_name="company_name_trgm_idx",
        ),
        migrations.AlterField(
            model_name="company",
            name="merged_into",
            field=models.ForeignKey(
                blank=True,
                help_text="The company this was merged into",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="merged_from_companies",
                to="company.company",
            ),
        ),
        # Constraints referencing a field must be removed (using the old field
        # name they were defined with) BEFORE the field is renamed, and any
        # replacement added AFTER: RenameField does not rewrite field names
        # embedded in Q() conditions on other constraints, so removing a
        # conditioned constraint after the rename fails to resolve the old
        # field name against the post-rename model state.
        migrations.RemoveConstraint(
            model_name="clientcontact",
            name="unique_client_contact_name",
        ),
        migrations.RenameField(
            model_name="clientcontact",
            old_name="client",
            new_name="company",
        ),
        migrations.AddConstraint(
            model_name="clientcontact",
            constraint=models.UniqueConstraint(
                fields=("company", "name"), name="unique_company_contact_name"
            ),
        ),
        migrations.RemoveConstraint(
            model_name="clientcontactmethod",
            name="client_contact_method_one_owner",
        ),
        migrations.RemoveConstraint(
            model_name="clientcontactmethod",
            name="unique_client_contact_method_value",
        ),
        migrations.RemoveConstraint(
            model_name="clientcontactmethod",
            name="unique_client_primary_contact_method",
        ),
        # These two constraints keep their names across the rename (they were
        # never named after "client"), but their conditions embed the old
        # field name too, so they need the same remove-before/add-after
        # treatment as the constraints above.
        migrations.RemoveConstraint(
            model_name="clientcontactmethod",
            name="unique_contact_contact_method_value",
        ),
        migrations.RemoveConstraint(
            model_name="clientcontactmethod",
            name="unique_contact_primary_contact_method",
        ),
        migrations.RenameField(
            model_name="clientcontactmethod",
            old_name="client",
            new_name="company",
        ),
        migrations.AddConstraint(
            model_name="clientcontactmethod",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("company__isnull", False), ("contact__isnull", True))
                    | models.Q(("company__isnull", True), ("contact__isnull", False))
                ),
                name="contact_method_one_owner",
            ),
        ),
        migrations.AddConstraint(
            model_name="clientcontactmethod",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("company__isnull", False), ("contact__isnull", True)
                ),
                fields=("company", "method_type", "normalized_value"),
                name="unique_company_contact_method_value",
            ),
        ),
        migrations.AddConstraint(
            model_name="clientcontactmethod",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("company__isnull", False),
                    ("contact__isnull", True),
                    ("is_primary", True),
                ),
                fields=("company", "method_type"),
                name="unique_company_primary_contact_method",
            ),
        ),
        migrations.AddConstraint(
            model_name="clientcontactmethod",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("company__isnull", True), ("contact__isnull", False)
                ),
                fields=("contact", "method_type", "normalized_value"),
                name="unique_contact_contact_method_value",
            ),
        ),
        migrations.AddConstraint(
            model_name="clientcontactmethod",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("company__isnull", True),
                    ("contact__isnull", False),
                    ("is_primary", True),
                ),
                fields=("contact", "method_type"),
                name="unique_contact_primary_contact_method",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="suppliersearchalias",
            name="unique_supplier_search_alias_per_client",
        ),
        migrations.RenameField(
            model_name="suppliersearchalias",
            old_name="client",
            new_name="company",
        ),
        migrations.AddConstraint(
            model_name="suppliersearchalias",
            constraint=models.UniqueConstraint(
                fields=("company", "alias"),
                name="unique_supplier_search_alias_per_company",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="supplierpickupaddress",
            name="unique_supplier_pickup_address_name",
        ),
        migrations.RenameField(
            model_name="supplierpickupaddress",
            old_name="client",
            new_name="company",
        ),
        migrations.AddConstraint(
            model_name="supplierpickupaddress",
            constraint=models.UniqueConstraint(
                fields=("company", "name"), name="unique_supplier_pickup_address_name"
            ),
        ),
    ]
