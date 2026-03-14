# Workshop My Time View Tests Plan

## Goals

- Add Playwright integration coverage for core Workshop My Time operations.
- Follow the existing `tests/` patterns for setup, helpers, and serial flows.

## Scope

- New spec under `tests/` targeting `src/views/WorkshopMyTimeView.vue`.
- Coverage for day navigation, refresh, add, update, and delete flows.

## Approach

1. Review existing Playwright tests and helpers for patterns to reuse.
2. Capture required selectors from Workshop My Time components.
3. Create a shared test job in `beforeAll` for the timesheet entries.
4. Write a serial suite covering:
   - previous/next day navigation
   - manual refresh for the day
   - add entry via calendar + job picker + save
   - update entry via calendar click + save
   - delete entry via drawer
5. Validate that the calendar event appears/updates/removes and that key API calls complete.

## Risks / Notes

- The calendar component has limited automation IDs; rely on role/text and `data-event-id`.
- Ensure waits key off API responses to avoid flaky timing.
