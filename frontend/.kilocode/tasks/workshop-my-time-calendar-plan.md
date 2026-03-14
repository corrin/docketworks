# Workshop My Time: Calendar-Style Day View Plan

## Goal

Refactor `src/views/WorkshopMyTimeView.vue` so each day renders as an hourly calendar (vertical timeline with hour ticks) while leveraging the new `start_time`/`end_time` keys that cost line endpoints now honor. Every create/edit must send these fields in addition to `hours`, and the modal workflow should make adjusting the period frictionless. When a response lacks either time, fall back to a simple table with an info card so legacy data still behaves predictably.

## Current State (today)

- `WorkshopMyTimeView.vue` shows a week overview plus a card list for the selected day—no grid/timeline.
- The view still assumes duration-only data coming from `GET/POST/PATCH/DELETE /job/api/workshop/timesheets/`.
- `WorkshopTimesheetEntry` exposes `hours`, accounting date, billing flags, and rate multiplier only; start/end data is not displayed.

## Functional/UX Requirements

1. **Day timeline view**
   - Vertical hours (00:00–24:00) rendered as a scrollable grid column; highlight business hours and show a current-time indicator on “today.”
   - Entries appear as stacked blocks spanning `start_time`→`end_time`, displaying job number/name, client, duration, billable badge, rate, and action icons.
   - Handle overlaps with lane assignment or slight offsets.
2. **Navigation**
   - Preserve the existing week selector; changing the selected day refreshes the calendar (or fallback table) immediately.
3. **Create/Edit modal**
   - Modal handles both create and edit flows: job picker, start time, end time, derived duration, description, billable toggle, rate multiplier, notes.
   - Quick actions for +/- 5/15/30 minutes, “Now,” “Fill gap,” and “Copy previous” respecting the table-like UX.
   - Delete action accessible from the modal.
4. **Interactions**
   - Clicking an empty slot pre-fills start/end rounded to the nearest 5–15 minutes and opens the modal.
   - Clicking an entry opens the edit modal; hover/focus should surface edit/delete icons that match the fallback table design.
   - Keyboard navigation: arrow keys move focus through hour rows, Enter opens the modal for that slot.
5. **Validation**
   - Enforce `start_time < end_time`, minimum duration of 1 minute (0.01 h), clamp to the active day, and warn about overlaps (even if they remain allowed).
6. **Accessibility & Responsiveness**
   - WCAG-friendly contrasts, touch-friendly hit boxes, tooltip descriptions for icon actions, and predictable tab order even inside the table fallback.

## Fallback UX for Legacy Entries

- Detect if any entry returned by the day query lacks `start_time` or `end_time`.
- When missing times exist:
  - Display an info card (shadcn Alert) explaining that the calendar view requires start/end times and that editing the entry will add them.
  - Replace the timeline with a slim table (`Job | Description | Hours | Billable | Rate | Actions`). The actions column includes pencil (edit modal) and trash (delete API) icons with tooltips and `sr-only` labels.
  - Once all entries in the day have times, automatically restore the calendar view; no manual toggle required.

## Data & API Considerations

- Cost line endpoints (Job cost set actuals + workshop endpoints) now accept `start_time` and `end_time`. Continue sending `hours` for compatibility until the backend derives it automatically.
- Normalize all times to strings in `HH:MM[:SS]` tied to the selected accounting date; store parsed minutes in local state for layout math.
- When persisting, include `job_id`, `accounting_date`, `start_time`, `end_time`, `hours`, `is_billable`, and `rate_multiplier`. The backend can derive totals, but front-end should not assume it.
- Older rows might omit the fields; keep the fallback path until the migration is complete.

## UI Composition Principles (table-friendly calendar)

- Use `@kodeglot/vue-calendar` in day mode but override its theme tokens (colors, borders, fonts) so the hourly grid visually matches our table surfaces; keep the hour column sticky like the rest of the app.
- Leverage the library’s custom template hooks to inject job/job number, duration, and inline action icons, keeping the same elevation/rounded styles as our cards.
- Provide a mini-legend above the calendar describing colors for billable/non-billable and overlapping lanes.
- When the fallback table is active, keep the same typography tokens and spacing so switching layouts feels seamless.

## Technical Approach (front-end)

1. **API client updates**
   - Regenerate `schema.yml`/OpenAPI client once backend includes the new fields; ensure zod schemas reference `start_time`/`end_time`.
   - Update local TypeScript types/composables to store the additional fields and send them in mutations.
2. **State shape**
   - Normalize entries to `{ id, jobId, jobNumber, jobName, clientName, description, isBillable, rateMultiplier, start, end, durationHours, hasTimes }`.
   - Derive `durationHours` from `start`/`end`; only fall back to server-provided `hours` when times are missing.
3. **Timeline layout (Vue Calendar)**
   - Integrate `@kodeglot/vue-calendar` (day view) to handle hourly breakdown, touch interactions, and overlap lanes out of the box.
   - Override theme variables/CSS so hour ticks, backgrounds, and typography align with our design system.
   - Use the calendar's slot/event hooks to show job/job number, description, duration, billable badge, and inline edit/delete icons that drive our modal/delete flows.
4. **Modal component**
   - Build or refactor a dedicated `WorkshopTimeEntryModal.vue` that encapsulates form state, validation, and quick adjust controls.
   - Prefill `end_time = start_time + defaultDuration` when creating from a timeslot; editing recalculates `hours` when times change.
5. **Interactions**
   - Support “Add entry” button plus click/tap on the calendar grid.
   - Provide tooltips/ARIA labels for timeline interactions to ensure the table-centric design remains accessible.
6. **Validation & guardrails**
   - Clamp times to the selected day; show inline errors in the modal if `start_time >= end_time` or entries overlap heavily.
   - Normalize to local time even if the backend returns UTC; handle DST transitions gracefully.
7. **Fallback handling**
   - Derived `hasTimes` flag toggles between timeline and table. Info card renders at the top of the day section.
   - Table rows reuse the modal for editing and the same delete confirmation flow.

## Task Breakdown

1. Confirm backend contract and regenerate schema/client (new `start_time`/`end_time` fields).
2. Update store/composable logic to persist and read the new fields; add `hasTimes` detection.
3. Install/configure `@kodeglot/vue-calendar`, add global styles, and theme the day view so it matches our table aesthetic.
4. Implement the enhanced modal (start/end controls, quick adjust buttons, derived duration).
5. Wire interactions (click-to-create, edit/delete icons, keyboard shortcuts) between the Vue calendar view and the modal/delete flows.
6. Implement fallback info card + table view when times are missing.
7. Validate/time math, overlapping logic, and DST handling.

## Open Questions

- Exact formatting of `start_time`/`end_time` (seconds vs minutes) and whether backend enforces timezone.  
  **Answer:** backend expects ISO time strings (HH:MM[:SS]) without an explicit timezone; they inherit the selected accounting date’s context.
  - `start_time` (string, ISO time): Start time of the timesheet entry.
  - `end_time` (string, ISO time): End time of the timesheet entry.
- Should the fallback info card include a CTA link to documentation or feature flag settings?  
  **Answer:** no CTA—just warn that the timeline can’t render because start/end time data is missing.
- Policy for overlapping entries: warn only, prevent save, or allow but highlight in UI?  
  **Answer:** allow overlaps, but issue a warning and visually highlight the overlapping blocks.
- Default duration when clicking empty slots (30 min vs last used) and whether it differs per staff.  
  **Answer:** default each new slot to 30 minutes regardless of staff; no per-user memory.
- Do we ever hide the table fallback (e.g., behind a flag) once data is migrated?  
  **Answer:** no—the fallback remains available permanently.

## Out of Scope (this iteration)

- Weekly/monthly calendar views.
- Drag-to-resize or drag-to-move interactions.
- Reporting/exports or advanced analytics from this screen.
