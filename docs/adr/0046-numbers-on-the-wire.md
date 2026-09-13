# 0046 — Numbers on the wire; the frontend owns all formatting

The API sends quantities as numbers — never currency symbols, thousands separators, percent signs, or any other display formatting. Formatting in the backend is a bug; ADR 0020's boundary is why.

## Rules

A schema field carrying money, a rate, a count or any other quantity is a
numeric type (`float`, `int`, `Decimal`). A display string on the wire poisons
every consumer that is not a display: the first frontend consumer to treat an
`f"${value:,.2f}"` field as a number renders `$NaN`.

The frontend formats at the point of display, through the shared formatters
in `frontend/src/lib/format.ts` (`formatCurrency`, `formatWholeCurrency`,
`formatPercentage`) — one formatter per precision concept, because E2E specs
assert cross-page string equality on formatted values, and two formatters for
one concept diverge invisibly. A report that offers a precision setting uses
`formatWholeCurrency` everywhere it shows money: the same figure rendering
`$1,234` in a cell and `$1,234.00` one click away is the divergence this rule
exists to prevent.

Units are part of the contract, not formatting. Rates travel in percentage
points (0–100, the scale `_rate()` in the accounting services produces);
money travels in dollars. Declare the unit in the field name or schema
description when it is not obvious — converting between units at a boundary
is fine, prettifying is not.

A schema declaring `str` for a quantity is the review smell that catches
this class. The legitimate string-typed value fields are identifiers,
enums, and text — things nobody will ever sum, sort numerically, or
reformat.

## Do not

- **Format server-side "because every consumer displays it"** — the next
  consumer is a CSV export, a sort key, or a test comparison, and it
  inherits a string it must parse back.
- **Send rates as 0–1 fractions to look more "pure"** — the repo-wide
  convention is percentage points; a second convention forces every
  consumer to know which fields carry which scale.
