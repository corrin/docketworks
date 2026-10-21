import { i18n } from '@/lib/i18n'

/** A `data`/`display_data` value as display text. The wire's `data: dict[str,
    object]` (apps/process/schemas.py) permits any JSON scalar, so TypeScript
    only ever sees it as `unknown` — bare `String()`/template interpolation
    on that would print `[object Object]` for anything non-primitive, so
    this picks the primitive cases explicitly and falls back to JSON rather
    than the object's default stringification. A checkbox reads Yes/No, not
    the stored true/false. */
export function textFor(value: unknown): string {
  if (value === undefined || value === null || value === '') return ''
  if (typeof value === 'boolean') {
    return value ? i18n.t('process:entryValue.yes') : i18n.t('process:entryValue.no')
  }
  if (typeof value === 'string' || typeof value === 'number') {
    return String(value)
  }
  return JSON.stringify(value)
}
