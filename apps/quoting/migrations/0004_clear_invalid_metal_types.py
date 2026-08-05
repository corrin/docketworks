"""Unset supplier-product metal types that were never valid choices.

Found by the same full-database validation sweep as
purchasing/0009. Thirteen `ProductParsingMapping` rows hold a
`mapped_metal_type` that has never appeared in `MetalType.choices`:
'unspecified' (ten rows), 'steel' (two) and 'tungsten' (one). The LLM parser
wrote them as free text and nothing validated the result, so these rows have
been unreadable to any consumer that trusts the choices.

They are set to NULL rather than remapped by hand. NULL is how this schema
spells "unset", and guessing would fabricate data: 'unspecified' means the
parser had no answer, a wire brush described as 'steel' is not a steel
product, and a tungsten TIG electrode has no home in the enum at all.

`parser_version` is cleared alongside, which is the deliberate re-run lever —
the end-of-run fill selects rows whose parser version is not the current one,
so these thirteen are re-derived properly on the next run instead of being
frozen as unset.

Rows an operator has hand-validated are excluded: their decision outranks the
parser (and this migration). All thirteen rows are currently unvalidated, so
the guard changes nothing today; it exists because this database keeps taking
writes until cutover and someone may validate one of these rows first.

Irreversible: reverse cannot recover a value it deliberately discarded as
invalid, so it is a no-op rather than a wrong restore (house pattern:
purchasing/0007_text_unset_is_null).
"""

from django.db import migrations

# apps.job.enums.MetalType.values — inlined because a migration must not
# import app code, which is free to change after this migration is frozen.
VALID_METAL_TYPES = (
    "stainless_steel",
    "mild_steel",
    "aluminium",
    "brass",
    "copper",
    "titanium",
    "zinc",
    "galvanized",
    "other",
)

_VALUE_LIST = ", ".join(f"'{value}'" for value in VALID_METAL_TYPES)


class Migration(migrations.Migration):
    dependencies = [
        ("quoting", "0003_text_unset_is_null"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "UPDATE quoting_productparsingmapping "
                "SET mapped_metal_type = NULL, parser_version = NULL "
                "WHERE mapped_metal_type IS NOT NULL "
                f"AND mapped_metal_type NOT IN ({_VALUE_LIST}) "
                "AND is_validated = false"
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
