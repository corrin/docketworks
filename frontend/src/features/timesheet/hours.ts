/**
 * Hours input parsing for the timesheet entry grid.
 *
 * v1-exact: entry habits like "1 1/4" must keep working for the workshop.
 * Its display counterpart is formatHoursDisplay in lib/format.ts.
 *
 * Opus: the formatter moved there once the KPI report needed it too — a
 * second hours formatter would diverge invisibly. The round-trip between the
 * two is asserted in hours.test.ts, where the parser lives.
 */

/**
 * Parse hours input. Accepts plain numbers, decimals, and fractional forms:
 * "1.5", "1 1/4", "3/4". Returns the existing fallback when input is blank
 * or unparseable, and clamps to [0, 24] (2dp).
 */
export function parseHoursInput(raw: string, fallback: number): number {
  const s = raw.trim()
  if (!s) return fallback
  let parsed: number
  const mixed = /^(\d+)\s+(\d+)\/(\d+)$/.exec(s)
  const frac = /^(\d+)\/(\d+)$/.exec(s)
  // The humanised display form must round-trip: the input SHOWS '3h 30m',
  // so a partial edit of that text must not parseFloat down to 3.
  const human = /^(?:(\d+)h)?\s*(?:(\d+)m)?$/.exec(s)
  if (human && (human[1] !== undefined || human[2] !== undefined)) {
    parsed = Number(human[1] ?? 0) + Number(human[2] ?? 0) / 60
    if (!Number.isFinite(parsed) || parsed < 0) return fallback
    return Math.round(Math.min(parsed, 24) * 100) / 100
  }
  if (mixed) {
    const whole = Number.parseInt(mixed[1]!, 10)
    const numerator = Number.parseInt(mixed[2]!, 10)
    const denominator = Number.parseInt(mixed[3]!, 10)
    if (denominator === 0) return fallback
    parsed = whole + numerator / denominator
  } else if (frac) {
    const numerator = Number.parseInt(frac[1]!, 10)
    const denominator = Number.parseInt(frac[2]!, 10)
    if (denominator === 0) return fallback
    parsed = numerator / denominator
  } else {
    parsed = Number.parseFloat(s)
  }
  if (!Number.isFinite(parsed) || parsed < 0) return fallback
  return Math.round(Math.min(parsed, 24) * 100) / 100
}
