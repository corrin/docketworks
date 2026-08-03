# 0020 — Frontend/Backend separation: data is backend, presentation is frontend

The boundary is the kind of value: database/business/external values are computed on the backend; layout and UI constants live in the frontend.

## Rules

- If a value involves the database, business rules, or an external system, the backend computes it and the frontend renders it as received — never recomputes it. That is what makes every total read the same in the screen, the export, and the database; a "just sum it locally" shortcut disagrees with the canonical figure the day someone runs a report.
- If a value is a static UI constant, layout, or ergonomics, it lives in the frontend. The backend never ships dropdown labels, never returns HTML, never shapes a response around what one screen happens to render — a new client (mobile, BI export) must be able to read exactly what the existing UI reads.
- When a UI need conflicts with this line, add a derived computation on the backend, not a frontend shortcut.
