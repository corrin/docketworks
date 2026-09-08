"""Prepare lost historical receipt evidence on a browser-created test line."""

import sys
from uuid import UUID

from scripts.bootstrap import setup_django

setup_django()

from django.db import connection, transaction  # noqa: E402

from adhoc.inventory_cost_repair import (  # noqa: E402
    ReceiptDisposition,
    RepairManifest,
    repair_receipt_gaps,
)
from apps.accounts.models import Staff  # noqa: E402
from apps.purchasing.models import PurchaseOrderLine  # noqa: E402


def main() -> None:
    """Confine fixture preparation to an unreceived, unlinked test draft."""
    if connection.settings_dict["NAME"].endswith("_prod"):
        raise ValueError("Legacy receipt E2E setup refuses production.")
    with transaction.atomic():
        line = (
            PurchaseOrderLine.objects.select_for_update()
            .select_related("purchase_order")
            .get(pk=UUID(sys.argv[1]))
        )
        if (
            not line.description.startswith("[TEST] legacy receipt")
            or line.received_quantity != 0
            or line.purchase_order.xero_id is not None
            or line.purchase_order.status != "draft"
            or line.stock_generated.exists()
        ):
            raise ValueError("Only an empty browser-created legacy receipt fixture may be seeded.")
        line.received_quantity = line.quantity
        line.save(update_fields=["received_quantity"])
        repair_receipt_gaps(
            RepairManifest(
                receipt_rows=[
                    ReceiptDisposition(
                        line_id=line.id,
                        received_quantity=line.received_quantity,
                        quantity=line.received_quantity,
                        reason=(
                            "Historical receipt evidence is missing; "
                            "recorded quantities are retained."
                        ),
                    )
                ]
            ),
            Staff.get_automation_user(),
            apply=True,
        )


if __name__ == "__main__":
    main()
