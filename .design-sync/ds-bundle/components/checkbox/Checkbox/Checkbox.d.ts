// Checkbox — boolean / tri-state checkbox. shadcn-vue wrapper over reka-ui CheckboxRoot.
// Source: frontend/src/components/ui/checkbox/Checkbox.vue

import type { DefineComponent } from 'vue'
import type { CheckboxRootProps, CheckboxRootEmits } from 'reka-ui'

export interface CheckboxProps extends /* reka-ui */ CheckboxRootProps {
  /** Controlled checked state. true | false | 'indeterminate'. */
  modelValue?: boolean | 'indeterminate'
  /** Uncontrolled initial state. */
  defaultValue?: boolean | 'indeterminate'
  disabled?: boolean
  required?: boolean
  name?: string
  value?: string
  id?: string
  /** Extra classes merged via cn(). */
  class?: string
}

export type CheckboxEmits = CheckboxRootEmits // includes (e:'update:modelValue', v: boolean|'indeterminate')

/**
 * @slot default — overrides the indicator glyph (defaults to a Check icon).
 */
export declare const Checkbox: DefineComponent<CheckboxProps>
