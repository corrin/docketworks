// Select — composable dropdown select. shadcn-vue wrappers over reka-ui Select primitives.
// Source: frontend/src/components/ui/select/*.vue
//
// Compose: Select > SelectTrigger(+SelectValue) + SelectContent > (SelectGroup >
//          SelectLabel + SelectItem...) [SelectSeparator, SelectScroll*Button].

import type { DefineComponent } from 'vue'
import type {
  SelectRootProps,
  SelectRootEmits,
  SelectContentProps,
  SelectContentEmits,
  SelectGroupProps,
  SelectItemProps,
  SelectItemTextProps,
  SelectLabelProps,
  SelectSeparatorProps,
  SelectValueProps,
  SelectTriggerProps,
  SelectScrollUpButtonProps,
  SelectScrollDownButtonProps,
} from 'reka-ui'

/** Root. Controlled via v-model:modelValue / v-model:open. */
export interface SelectProps extends SelectRootProps {
  modelValue?: string | string[]
  defaultValue?: string | string[]
  open?: boolean
  disabled?: boolean
  multiple?: boolean
  name?: string
}
export type SelectEmits = SelectRootEmits

/** The button that opens the listbox. */
export interface SelectTriggerProps_ extends SelectTriggerProps {
  /** Height token: 'default' (h-9) | 'sm' (h-8). Default 'default'. */
  size?: 'sm' | 'default'
  class?: string
}

/** Displays the selected value; takes a `placeholder`. */
export interface SelectValueProps_ extends SelectValueProps {
  placeholder?: string
}

/** Floating popover containing the options. position defaults to 'popper'. */
export interface SelectContentProps_ extends SelectContentProps {
  position?: 'item-aligned' | 'popper'
  class?: string
}
export type SelectContentEmits_ = SelectContentEmits

export interface SelectGroupProps_ extends SelectGroupProps {}
export interface SelectLabelProps_ extends SelectLabelProps {
  class?: string
}
export interface SelectItemProps_ extends SelectItemProps {
  /** Required value for this option. */
  value: SelectItemProps['value']
  disabled?: boolean
  class?: string
}
export interface SelectItemTextProps_ extends SelectItemTextProps {}
export interface SelectSeparatorProps_ extends SelectSeparatorProps {
  class?: string
}
export interface SelectScrollUpButtonProps_ extends SelectScrollUpButtonProps {
  class?: string
}
export interface SelectScrollDownButtonProps_ extends SelectScrollDownButtonProps {
  class?: string
}

/** @slot default — SelectTrigger + SelectContent. */
export declare const Select: DefineComponent<SelectProps>
/** @slot default — SelectValue / icons. Default-slot before the chevron icon. */
export declare const SelectTrigger: DefineComponent<SelectTriggerProps_>
/** Renders the current value or placeholder text. */
export declare const SelectValue: DefineComponent<SelectValueProps_>
/** @slot default — items, groups, labels, separators. */
export declare const SelectContent: DefineComponent<SelectContentProps_>
/** @slot default — groups SelectItems under an optional SelectLabel. */
export declare const SelectGroup: DefineComponent<SelectGroupProps_>
/** @slot default — non-selectable group heading. */
export declare const SelectLabel: DefineComponent<SelectLabelProps_>
/** @slot default — option label; shows a Check indicator when selected. */
export declare const SelectItem: DefineComponent<SelectItemProps_>
/** @slot default — explicit text node for an item. */
export declare const SelectItemText: DefineComponent<SelectItemTextProps_>
/** Thin horizontal divider between groups. */
export declare const SelectSeparator: DefineComponent<SelectSeparatorProps_>
/** ChevronUp scroll affordance (auto-rendered inside SelectContent). */
export declare const SelectScrollUpButton: DefineComponent<SelectScrollUpButtonProps_>
/** ChevronDown scroll affordance (auto-rendered inside SelectContent). */
export declare const SelectScrollDownButton: DefineComponent<SelectScrollDownButtonProps_>
