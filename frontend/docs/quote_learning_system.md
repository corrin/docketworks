# Quote Insight Engine – RAG-Style Historical Lookup

## Purpose

Support estimators with context from similar past jobs by retrieving previous quotes and actual outcomes for comparison. This is not an AI-driven predictor but a deterministic, retrieval-augmented quoting insight tool.

## Objectives

- Help estimators detect quoting inconsistencies or risk factors early
- Surface real-world labor/material usage from similar jobs
- Encourage reuse of validated logic from past work
- Improve margin discipline and estimation accuracy

---

## Functional Overview

### 1. Inputs

- Parsed metadata from current estimate, including:
  - Dimensions (e.g. 700×700×400)
  - Material (type, finish, gauge)
  - Fabrication method (e.g. TIG welded)
  - Quantity
- Optionally: customer, job type, job number

### 2. Retrieval Strategy

- Match against a historical database of quotes and actuals
- Index jobs by:
  - Material type and finish
  - Fabrication method
  - Size bucket (e.g. 600–800 mm)
  - Part type if available (tray, box, plate)
  - Customer (optional weight)

### 3. Returned Data

For each match (up to N=5):

- Job ID or Quote Reference
- Quoted material used (e.g. 1.75 sheets)
- Actual material used (if available)
- Quoted labor time and cost
- Actual labor time and cost
- Supplier and unit prices (if tracked)
- Margin (quoted vs actual)
- Estimator comments (if any)

### 4. Presentation

Displayed in a table for estimator review. Example:

| Quote  | Part Desc    | Material     | Qty | Sheets (Q/A) | Labor (Q/A) | Margin | Notes                         |
| ------ | ------------ | ------------ | --- | ------------ | ----------- | ------ | ----------------------------- |
| Q-0071 | 600x600 tray | 304/4, 1.2mm | 4   | 1.8 / 2.0    | 2.4 / 2.9   | 16.3%  | Slight under on folding labor |
| Q-0112 | 700x700 box  | 304/4, 1.2mm | 3   | 2.0 / 2.0    | 3.6 / 3.6   | 19.4%  | Used Rivtec stainless         |

### 5. Estimator Use

- Manual trigger: “🔎 Compare to Similar Jobs” button
- Used to validate quote inputs, sheet usage assumptions, and pricing consistency
- Optionally annotate current quote with reasoning or overrides

---

## Technical Notes

- Retrieval does not use AI inference — just deterministic filters + scoring
- Optional weighting: material = 40%, dimensions = 30%, method = 30%
- No automatic quote adjustments made — this is an _insight tool only_

---

## Future Extensions

- Job tagging to improve part type similarity detection
- Estimator post-job comments integrated into matches
- Time-series report: material usage/quote deviation trends
