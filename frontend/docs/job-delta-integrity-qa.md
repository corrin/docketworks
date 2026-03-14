# Job Delta Integrity – QA Checklist

Use this guide to verify the new delta envelope autosave flow for Job headers.

## Automated checks

- `npx vitest run src/utils/__tests__/deltaChecksum.test.ts` – checksum canonicalisation parity

## Manual checks

1. Load a Job in `JobView` and update the header name; confirm autosave success toast and the backend records a Job event change id.
2. Change the client and verify the contact fields clear on the server (inspect Job detail view or reload). Confirm the delta toast shows success.
3. Open the same Job in two tabs. Change the name in tab A, then update status in tab B after tab A saves. Ensure tab B receives the concurrency toast and that hitting Retry resubmits successfully.
4. Toggle quoted/paid switches rapidly; the autosave queue should coalesce into sequential deltas without duplicate change ids (check devtools log if `devLogging` enabled).
5. Go offline (disable network), edit the header, and confirm autosave reports failure without sending an invalid delta. Re-enable network and Retry to ensure the original change id is reused.

Document test results in your PR description along with the impacted Job ids for support cross-reference.
