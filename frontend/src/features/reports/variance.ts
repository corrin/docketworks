/**
 * The sales forecast's variance banding. Bands are percentage points
 * (ADR 0046).
 *
 * Opus: deliberately not yet claimed as the shared home for every two-system
 * comparison — payroll reconciliation renders its own difference with no tone
 * at all, and JobFinishTab's green/red carries a polarity this has no concept
 * of. It moves to features/shared on the slice that adopts it, not on the
 * promise of one.
 */

const CLOSE_ENOUGH_PCT = 10
const WORTH_A_LOOK_PCT = 25

/**
 * Opus: a variance report exists to make the month that drifted visible at a
 * glance, so the badge colour is the answer and the number is the evidence.
 * Banded on absolute drift: over-billing by a third is as much worth opening
 * as under-billing by a third.
 */
export function varianceBadgeClass(variancePct: number): string {
  const drift = Math.abs(variancePct)
  if (drift < CLOSE_ENOUGH_PCT) return 'bg-green-100 text-green-800'
  if (drift < WORTH_A_LOOK_PCT) return 'bg-yellow-100 text-yellow-800'
  return 'bg-red-100 text-red-800'
}

/** Green above the line, red below it — sign only, no threshold. */
export function varianceToneClass(variance: number): string {
  return variance >= 0 ? 'text-green-600' : 'text-red-600'
}
