import type { KpiDayDataOut, KpiMonthlyTotalsOut } from '@/api'
import { formatCurrency, formatPercentage, formatWholeCurrency } from '@/lib/format'

/** The day's grade, straight off the wire: three rungs plus the ungraded weekend. */
export type DayCategory = KpiDayDataOut['color_hours']

/** The month's grade: a month is never a weekend. */
export type DayColor = KpiMonthlyTotalsOut['color_hours']

/** Which ladder tints the calendar. Hours is the default (owner ruling
    2026-09-01): dollars are the goal but a noisy daily signal, while billed
    hours lead them. */
export type KpiTarget = 'hours' | 'dollars'

/** Money precision for the WHOLE report (Xero's model: the choice belongs to
    the report, not the column). */
export type KpiDecimals = 0 | 2

export type MoneyFormatter = (value: number) => string

/**
 * The one money formatter the report uses, chosen once from the URL setting
 * and passed down, so a cell cannot render $1,234 beside a dialog showing
 * $1,234.00 for the same figure.
 */
export function moneyFormatter(decimals: KpiDecimals): MoneyFormatter {
  return decimals === 0 ? formatWholeCurrency : formatCurrency
}

/**
 * A served ratio, or the blank that says there was no denominator. The server
 * sends null for a margin on zero revenue because 0% would read as break-even;
 * the blank keeps that distinction on screen.
 */
export function ratioText(value: number | null): string {
  return value === null ? '—' : formatPercentage(value)
}

/** A served rate, or the same blank. */
export function moneyText(value: number | null, money: MoneyFormatter): string {
  return value === null ? '—' : money(value)
}

export function dayCategory(day: KpiDayDataOut, target: KpiTarget): DayCategory {
  return target === 'hours' ? day.color_hours : day.color_gp
}

export function monthColor(totals: KpiMonthlyTotalsOut, target: KpiTarget): DayColor {
  return target === 'hours' ? totals.color_hours : totals.color_gp
}

/**
 * What a grade means, in words. Colour never carries state alone
 * (docs/design-language.md): every tinted surface also says this.
 */
export const GRADE_WORDING: Record<DayCategory, string> = {
  green: 'On target',
  amber: 'Close',
  red: 'Behind',
  weekend: 'Weekend',
}

/** Surface, border and ink for a graded cell or card. A Record over the
    wire's closed set, so a fifth category is a compile error here rather
    than a silently untinted cell. */
const TONE_CLASS: Record<DayCategory, string> = {
  green: 'border-green-200 bg-green-50 text-green-900',
  amber: 'border-amber-200 bg-amber-50 text-amber-900',
  red: 'border-red-200 bg-red-50 text-red-900',
  weekend: 'border-gray-200 bg-white text-gray-600',
}

export function kpiToneClass(category: DayCategory): string {
  return TONE_CLASS[category]
}

/** Ink alone, for a word or figure inside an untinted surface. */
const INK_CLASS: Record<DayCategory, string> = {
  green: 'text-green-700',
  amber: 'text-amber-700',
  red: 'text-red-700',
  weekend: 'text-gray-500',
}

export function kpiInkClass(category: DayCategory): string {
  return INK_CLASS[category]
}

/** Positive money in green ink, negative in red: the one sign treatment. */
export function signClass(value: number): string {
  return value < 0 ? 'text-red-700' : 'text-green-700'
}

/** The month's days in date order; the wire keys them by date but a
    JavaScript object promises no order. */
export function sortedDays(calendar: Record<string, KpiDayDataOut>): KpiDayDataOut[] {
  return Object.values(calendar).toSorted((a, b) => a.date.localeCompare(b.date))
}
