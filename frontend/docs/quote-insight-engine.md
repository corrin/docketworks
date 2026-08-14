# Quote Insight Engine — RAG-Style Historical Lookup

**Status: unimplemented design.** No code exists for this feature — not in the
current codebase and not in the system it replaced. It is retained as a product
design note because the estimating problem it addresses is real. If it is ever
built, it belongs in the quoting domain (`apps/quoting` + a
`features/quoting`-adjacent frontend feature) and its retrieval is deterministic
database work, not an LLM call — if any AI assistance is added later, it goes
through the single LLM gateway (ADR 0041).

## Purpose

Support estimators with context from similar past jobs by retrieving previous
quotes and actual outcomes for comparison. This is not an AI-driven predictor
but a deterministic, retrieval-augmented quoting insight tool.

## Objectives

- Help estimators detect quoting inconsistencies or risk factors early
- Surface real-world labour/material usage from similar jobs
- Encourage reuse of validated logic from past work
- Improve margin discipline and estimation accuracy

## Functional overview

### 1. Inputs

- Parsed metadata from the current estimate:
  - Dimensions (e.g. 700x700x400)
  - Material (type, finish, gauge)
  - Fabrication method (e.g. TIG welded)
  - Quantity
- Optionally: customer, job type, job number

### 2. Retrieval strategy

- Match against historical quotes and actuals
- Index jobs by material type and finish, fabrication method, size bucket
  (e.g. 600–800 mm), part type if available (tray, box, plate), and optionally
  customer

### 3. Returned data

For each match (up to N=5): job/quote reference, quoted vs actual material
used, quoted vs actual labour time and cost, supplier and unit prices where
tracked, margin (quoted vs actual), and estimator comments.

### 4. Presentation

A table for estimator review:

| Quote | Part Desc | Material | Qty | Sheets (Q/A) | Labour (Q/A) | Margin | Notes |
|---|---|---|---|---|---|---|---|
| Q-0071 | 600x600 tray | 304/4, 1.2mm | 4 | 1.8 / 2.0 | 2.4 / 2.9 | 16.3% | Slight under on folding labour |
| Q-0112 | 700x700 box | 304/4, 1.2mm | 3 | 2.0 / 2.0 | 3.6 / 3.6 | 19.4% | Used Rivtec stainless |

### 5. Estimator use

- Manual trigger: a "Compare to Similar Jobs" action
- Used to validate quote inputs, sheet-usage assumptions, and pricing
  consistency
- No automatic quote adjustments — this is an insight tool only

## Technical notes

- Retrieval is deterministic filters plus scoring; no inference
- Optional weighting: material 40%, dimensions 30%, method 30%

## Future extensions

- Job tagging to improve part-type similarity detection
- Estimator post-job comments integrated into matches
- Time-series report: material usage / quote deviation trends
