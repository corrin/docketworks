---
title: Create a Purchase Order
---

# Create a Purchase Order

> **When to use:** You need to order materials or supplies from a supplier for a job.

## What You'll Need

- [ ] Supplier details (must be set up in the system)
- [ ] List of items to order (descriptions, quantities, costs)
- [ ] The job number to allocate the purchase against

## Steps

### 1. Create a new PO

Navigate to **Purchases > Purchase Orders** in the navbar, then click **New Purchase Order**.

<!-- PLACEHOLDER: Screenshot showing the Purchase Orders list page -->

Fill in the basic details:

- **Supplier** -- Select from the dropdown. Must match an existing supplier.
- **Reference** -- Your internal reference or the supplier's quote number.
- **Expected Delivery Date** -- When you expect the goods to arrive.
- **Pickup Address** -- If applicable, where the goods will be picked up from.

Click **Save** to create the PO and open it for editing.

### 2. Add line items

<!-- PLACEHOLDER: Screenshot showing the PO line items table with example entries -->

In the line items table, add each item you're ordering:

| Field           | What it means                            |
| --------------- | ---------------------------------------- |
| **Item Code**   | The supplier's product code              |
| **Description** | What you're ordering                     |
| **Quantity**    | How many                                 |
| **Unit Cost**   | Price per unit                           |
| **Price TBC**   | Tick this if you don't know the cost yet |
| **Job**         | Which job this item is for               |

You can assign different line items to different jobs on the same PO.

### 3. Review and submit

Check the totals and make sure everything looks right. When you're ready, change the status from **Draft** to **Submitted**.

<!-- PLACEHOLDER: Screenshot showing the PO summary card with status dropdown -->

Once submitted, the supplier and line items are locked -- you can still update delivery dates and pickup addresses, but the core order details are fixed.

### 4. Send to the supplier

Use the **Email** button to send the PO to the supplier via email, or **Print** to generate a PDF you can send manually.

If the supplier is set up in Xero, you can use the **Sync with Xero** button to push the PO through to Xero as well.

### 5. Record deliveries

As goods arrive, update the received quantities on each line item. The PO status will automatically move from "Submitted" to "Partially Received" and finally "Fully Received" as you record deliveries.

## What Happens Next

- The PO is tracked in the system with a clear status (Draft → Submitted → Partially Received → Fully Received)
- Costs are allocated against the job(s) specified on each line
- If synced to Xero, the PO appears there for accounting purposes
- Material costs flow through to the job's Reality section and into the KPI reports

## Tips

::: tip
Use the **Price TBC** checkbox when you know you need to order something but are waiting on a price. This lets you get the order started without holding things up.
:::

::: tip
Add comments on the PO using the comments section at the bottom. This is handy for tracking conversations with the supplier about delivery changes, back-orders, etc.
:::

::: warning
Once a PO is submitted, you can't change the supplier or line items. If you need to make changes, you'll need to delete the PO and create a new one. Double-check before submitting.
:::
