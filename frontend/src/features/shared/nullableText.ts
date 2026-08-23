/**
 * The wire's NullableText, from the form's side.
 *
 * ADR 0040: an emptied optional box is unset, and unset is null. The request
 * schemas declare these fields as nullable-and-non-blank, so sending '' is a
 * 422 — every form with an optional text box needs this same conversion, and
 * one home for it means a new form cannot quietly ship the old spelling.
 */
export const orNull = (value: string): string | null => (value.trim() === '' ? null : value)
