"""Apply individually reviewed receipt-reference dispositions before inventory cutover.

Run with a private JSON manifest and --database naming the target. Preview is
read-only; --apply validates the entire manifest before changing any row.
Client identifiers belong in the manifest, never in this public mechanism (ADR 0049).
"""

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from scripts.bootstrap import setup_django

setup_django()

from django.db import connection, transaction  # noqa: E402 -- configure Django before model imports

from apps.job.models.costing import CostLine  # noqa: E402 -- Django setup precedes models
from apps.purchasing.models import PurchaseOrderLine, StockMovement  # noqa: E402


class Disposition(BaseModel):
    """An approved identity and amount; no candidate search happens during apply."""

    model_config = ConfigDict(extra="forbid")
    cost_id: UUID
    purchase_order_id: UUID
    dead_line_id: UUID
    job_number: int
    quantity: Decimal
    unit_cost: Decimal
    replacement_line_id: UUID | None = None
    reason: str = Field(min_length=1)


class RepairManifest(BaseModel):
    """A private, reviewed list of exact repairs."""

    model_config = ConfigDict(extra="forbid")
    rows: list[Disposition] = Field(min_length=1)


def evidence(disposition: Disposition, line: CostLine) -> str:
    """Preserve the former classification and references in the existing comments field."""
    return json.dumps(
        {
            "inventory_cutover_disposition": disposition.model_dump(mode="json"),
            "original_kind": line.kind,
            "original_ext_refs": line.ext_refs,
            "original_meta": line.meta,
        },
        sort_keys=True,
    )


def already_applied(disposition: Disposition, line: CostLine) -> bool:
    """Recognise only the exact reviewed disposition recorded by this repair."""
    comments = line.meta.get("comments")
    if not isinstance(comments, str) or not comments.startswith(
        '{"inventory_cutover_disposition":'
    ):
        return False
    recorded = json.loads(comments)
    return bool(recorded["inventory_cutover_disposition"] == disposition.model_dump(mode="json"))


def validate_disposition(disposition: Disposition, line: CostLine) -> bool:
    """Validate the booked position and explicit replacement; return whether work remains."""
    if (
        line.cost_set.kind != "actual"
        or line.cost_set.job.job_number != disposition.job_number
        or line.quantity != disposition.quantity
        or line.unit_cost != disposition.unit_cost
    ):
        raise ValueError(f"Booked position changed for {line.id}; review the manifest again.")
    if already_applied(disposition, line):
        return False
    if line.kind != "material" or not line.approved or line.managed_by is not None:
        raise ValueError(f"Cost {line.id} is not an unowned historical material charge.")
    if StockMovement.objects.filter(cost_line=line).exists():
        raise ValueError(f"Cost {line.id} already has protected inventory evidence.")
    if (
        line.ext_refs.get("purchase_order_id") != str(disposition.purchase_order_id)
        or line.ext_refs.get("purchase_order_line_id") != str(disposition.dead_line_id)
        or PurchaseOrderLine.objects.filter(pk=disposition.dead_line_id).exists()
    ):
        raise ValueError(f"Cost {line.id} no longer has the reviewed dangling reference.")
    if disposition.replacement_line_id is None:
        return True
    replacement = PurchaseOrderLine.objects.select_related("job").get(
        pk=disposition.replacement_line_id
    )
    if (
        replacement.purchase_order_id != disposition.purchase_order_id
        or replacement.job_id != line.cost_set.job_id
        or replacement.quantity != line.quantity
        or replacement.received_quantity != line.quantity
        or replacement.unit_cost != line.unit_cost
        or replacement.xero_description != f"{disposition.job_number} - {line.desc}"
        or CostLine.objects.filter(ext_refs__purchase_order_line_id=str(replacement.id)).exists()
        or replacement.stock_generated.exists()
    ):
        raise ValueError(f"Replacement {replacement.id} no longer matches the reviewed evidence.")
    return True


@transaction.atomic
def repair(manifest: RepairManifest, *, apply: bool) -> int:
    """Validate every selected row before applying an atomic, repeatable reclassification."""
    ids = [row.cost_id for row in manifest.rows]
    if len(set(ids)) != len(ids):
        raise ValueError("A cost may have only one reviewed disposition.")
    lines = CostLine.objects.select_related("cost_set__job").filter(pk__in=ids).order_by("id")
    if apply:
        lines = lines.select_for_update(of=("self",))
        list(
            PurchaseOrderLine.objects.select_for_update()
            .filter(purchase_order_id__in=[row.purchase_order_id for row in manifest.rows])
            .order_by("id")
        )
    by_id = {line.id: line for line in lines}
    if set(by_id) != set(ids):
        raise ValueError("The manifest names costs absent from this database.")
    pending = [row for row in manifest.rows if validate_disposition(row, by_id[row.cost_id])]
    if not apply:
        return len(pending)
    for row in pending:
        line = by_id[row.cost_id]
        comments = evidence(row, line)
        if row.replacement_line_id is None:
            line.kind = "adjust"
            line.ext_refs = {}
            line.meta = {"source": "manual_adjustment", "comments": comments}
        else:
            line.ext_refs["purchase_order_line_id"] = str(row.replacement_line_id)
            line.meta = line.meta | {"comments": comments}
        line.save(update_fields=["kind", "ext_refs", "meta", "updated_at"])
    return len(pending)


def main() -> None:
    """Require an explicit database identity even for preview."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--database", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if connection.settings_dict["NAME"] != args.database:
        raise ValueError("Configured database does not match --database.")
    manifest = RepairManifest.model_validate_json(args.manifest.read_text())
    count = repair(manifest, apply=args.apply)
    sys.stdout.write(f"{'Applied' if args.apply else 'Validated'} {count} reviewed dispositions.\n")


if __name__ == "__main__":
    main()
