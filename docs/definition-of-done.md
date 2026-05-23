# Definition of Done

This checklist applies before a Trello/Jira ticket is considered complete and
ready to close. It captures the former Trello `Coding standards (REMINDER)`
column as process guidance rather than migratable work.

## Required Checks

- Review the browser JavaScript console for warnings or errors in the affected
  workflows.
- Review the Django/server console for warnings or errors in the affected
  workflows.
- Run the relevant frontend and backend checks for the touched area, and do not
  leave new build, type-check, schema, or OpenAPI warnings unexplained.
- Check for weak frontend typing such as avoidable `any` or loose passthrough
  types.
- Regression-test the user workflow that the change touches, not only the
  specific failing assertion or code path.
- Confirm the business workflow still makes sense for the people using it. For
  user-facing releases, check with the relevant business user after release when
  the change affects their daily flow.

## Notes

- Existing known warnings must be explicitly identified if they are not fixed in
  the current ticket.
- Manual regression notes are acceptable when automated coverage is impractical,
  but the ticket should say what was checked.
- Do not close a ticket solely because the code compiles; close it when the
  relevant workflow is coherent and verified.
