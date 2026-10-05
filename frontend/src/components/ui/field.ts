/**
 * The one class string for plain form fields (raw <input>/<select>) outside
 * the Radix-backed controls. Three dialogs each carried a private copy, and
 * one had already drifted a padding step from the other two.
 *
 * 16px below `md`, 14px from there up: iOS Safari zooms the page when a
 * focused field's text is smaller than 16px, and a phone is where workshop
 * staff type into these.
 */
export const INPUT_CLASS =
  'w-full rounded-md border border-slate-300 px-3 py-2 text-base md:text-sm'
