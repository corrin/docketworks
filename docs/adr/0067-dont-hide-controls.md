# 0067 — A control never disappears because it cannot be used now; it disables and says why
Unratified: Opus

A user who learned where a button is and finds it gone cannot tell "not now" from "broken" or
"moved", and stops trusting the screen. So a control that belongs on a screen is always there;
when the data or state means it cannot be used, it is disabled and tells the user why.

## Rules

- **Render the control; disable it.** A button, link, menu item, tab or field that a screen
  offers is not wrapped in `cond && …`, a ternary to `null`, an early `return null` or a
  state-toggled `hidden` because of the record's status, an empty collection, a zero value or
  work already done. It renders with `disabled` instead.
- **A disabled control says why, in its own text where it fits.** "No time to sweep",
  "Nothing to invoice", "Already approved". Button text is read on a phone, where nothing
  hovers. Where the reason does not fit, keep the action's label and put the reason in a
  `title` (or the shared tooltip, once one exists), and give the disabled control an
  accessible description carrying the same words.
- **A swap is not a hide.** One control that changes to its counterpart in the same place —
  Reject job ↔ Reopen job, Edit ↔ Save/Cancel, Save ↔ Saving… — keeps the place and the purpose,
  and is allowed.
- **Pending is shown on the control, not by removing it.** While a request runs, the control
  stays, disabled, with its pending words ("Saving…", "Checking…").
- **Content follows the same rule.** A section, column or summary that the screen offers says
  "None" or "Nothing to …" when it is empty, rather than vanishing (docs/design-language.md
  distinguishes empty from loading and failed).
- **Responsive placement is not hiding.** A control that moves to another position at another
  breakpoint is still on the screen.

## Do not

- **Hide the action to keep the screen tidy** — the tidiness costs the user the knowledge that
  the action exists and where it lives; a disabled control with its reason costs one line.
