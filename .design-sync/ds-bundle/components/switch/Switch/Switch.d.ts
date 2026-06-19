// Switch — on/off toggle. shadcn-vue wrapper over reka-ui SwitchRoot.
// Source: frontend/src/components/ui/switch/Switch.vue

import type { DefineComponent } from 'vue'
import type { SwitchRootProps, SwitchRootEmits } from 'reka-ui'

export interface SwitchProps extends /* reka-ui */ SwitchRootProps {
  /** Controlled checked state. */
  modelValue?: boolean
  /** Uncontrolled initial state. */
  defaultValue?: boolean
  disabled?: boolean
  required?: boolean
  name?: string
  value?: string
  id?: string
  /** Extra classes merged via cn(). */
  class?: string
}

export type SwitchEmits = SwitchRootEmits // includes (e:'update:modelValue', v: boolean)

/**
 * @slot thumb — optional content rendered inside the sliding thumb.
 */
export declare const Switch: DefineComponent<SwitchProps>
