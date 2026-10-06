/**
 * A 44px tap area on phone-width screens, for the controls workshop staff
 * work by thumb. The shared default is 36px (docs/design-language.md), which
 * is right for a pointer; this is the one deliberate override of it, kept in
 * one place so every workshop surface grows the same way. `sm` and wider is
 * untouched.
 */
export const TOUCH_TARGET_CLASS =
  'max-sm:inline-flex max-sm:min-h-11 max-sm:min-w-11 max-sm:items-center'
