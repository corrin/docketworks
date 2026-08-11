/** Text is pinned to exactly "Save failed" — an E2E spec asserts it verbatim. */
export function SaveFailedBadge() {
  return (
    <span className="inline-block rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
      Save failed
    </span>
  )
}
