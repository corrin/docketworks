# Quote Output Columns – Structured Breakdown

This document outlines the required structure for the final quote table, aligned to the existing spreadsheet format used by the estimating team.

---

## 🔢 Base Fields

| Column        | Description                                |
| ------------- | ------------------------------------------ |
| `item`        | Sequence number (for display/order)        |
| `type`        | Either `labour` or `materials`             |
| `description` | Freeform description or internal item code |

---

## 🔧 For Labour Rows

Only the following fields are populated:

| Column       | Description                                   |
| ------------ | --------------------------------------------- |
| `labour`     | Time in minutes for in-house fabrication work |
| `total cost` | Calculated = labour mins × hourly rate        |
| `item cost`  | Duplicate - labour is always quantity 1       |

Other material-specific columns are left blank.

---

## 🧱 For Material Rows

The following fields are populated:

| Column             | Description                                    |
| ------------------ | ---------------------------------------------- |
| `quantity`         | Quantity of parts                              |
| `supplier`         | Supplier Name                                  |
| `supplier_part_no` | Supplier Part ID                               |
| `our_part_no`      | Our Item Id. Supports recursion                |
| `thickness`        | Material thickness (e.g. 1.2 mm)               |
| `Materials`        | Material spec (e.g. 304/4 stainless)           |
| `fold cost`        | Calculated or fixed cost per fold              |
| `fold set up fee`  | One-time setup cost for folding                |
| `hole costs`       | Cost based on hole quantity/type               |
| `welding cost`     | Per part or total welding cost                 |
| `Materials cost`   | Total cost of raw material (e.g. sheet × rate) |
| `Tube`             | Description and quantity of RHS/SHS/pipe used  |
| `Prep`             | Prep notes (e.g. polished edges, finish level) |
| `total cost`       | All material-related costs combined            |
| `item cost`        | `total cost ÷ quantity`                        |

Labour-specific fields (e.g. `labour`) remain blank.

---

## 📝 Optional Notes

| Column           | Description                                |
| ---------------- | ------------------------------------------ |
| `customer notes` | Any estimator-entered comment for customer |

---

## 📤 Use in Export

- Exported to CSV or spreadsheet with consistent column order
- Includes one row per quote item (labour or material)
- You cannot have labour and materials on the same row
- Output mirrors estimator-visible tables during quote assembly

---
