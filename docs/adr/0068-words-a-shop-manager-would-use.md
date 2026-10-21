# 0068 — Every word on a screen is one a sheet metal shop manager would use
Unratified: Opus

The people using Docketworks run and work in a sheet metal shop. Every word they read —
labels, buttons, messages, tooltips, errors — explains what's going on the way the manager
would tell someone about it.

## Rules

- **Say it the way the manager would say it out loud:** "Book leftover time to General work",
  "All time is on jobs".
- **Name things the way the shop names them.** Code names, ticket words and vendor terms stay
  in the code.
- **Use the word in [`docs/glossary.md`](../glossary.md).** A screen that needs a new word adds
  it there in the same change, so one thing has one name everywhere.
- **A word that can still be read two ways carries a tooltip saying exactly what it covers.**
  "Wages including paid leave" explains on hover that it is wages plus holiday, sick and
  public-holiday pay, spread over the hours worked. The tooltip text lives in the catalogue
  beside the word (ADR 0069).
