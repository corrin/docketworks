/**
 * The badge a draft row wears after a failed persist, until a retry lands.
 * The E2E contract asserts this exact text on the row.
 */
export function SaveFailedBadge() {
  return (
    <span className="inline-block rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
      Save failed
    </span>
  )
}
