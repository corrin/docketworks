# 0069 — The words on a screen live in the English catalogues
Unratified: Opus

Every word a user reads comes from a catalogue, so the app's wording can be read, discussed
and changed in one place.

## Rules

- **The frontend's words live in `frontend/src/locales/en/<area>.json`** and reach the screen
  through react-i18next's `t()`, with keys named for what the text means
  (`xero.updateButton`). Labels, buttons, headings, tooltips, placeholders, toasts, empty
  states, dialog text, error fallbacks and aria labels all go there; so do the display names
  for codes (`in_progress` → "In Progress"). A missing key fails `npm run type-check`.
- **The backend's words for users are wrapped in Django gettext** (`gettext`, `gettext_lazy`):
  typed refusals, validation messages, choice labels, `verbose_name` and `help_text`. Their text
  stays in the code; `locale/en_NZ/LC_MESSAGES/django.po` lists them and is regenerated on
  commit.
- **Text that only reaches a screen through a bug** — an unexpected exception shown with its
  reference (ADR 0038), an assertion inside the code — stays plain, because it is written for
  whoever fixes the bug.
- **The words themselves follow ADR 0068 and [`docs/glossary.md`](../glossary.md).** A wording
  change is an edit to the catalogue, with the screen's tests changed in the same commit.
