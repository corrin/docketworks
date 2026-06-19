// Input — single-line text field. shadcn-vue wrapper over a native <input>.
// Source: frontend/src/components/ui/input/Input.vue

import type { DefineComponent } from 'vue'

export interface InputProps {
  /** Initial value when uncontrolled. */
  defaultValue?: string | number
  /** v-model value. */
  modelValue?: string | number
  /** Extra classes merged via cn(). */
  class?: string
  // Native <input> attributes (type, placeholder, disabled, readonly,
  // aria-invalid, name, id, etc.) are passed through via fallthrough attrs.
}

export interface InputEmits {
  (e: 'update:modelValue', payload: string | number): void
}

/**
 * @slot (none) — renders a native <input data-slot="input">.
 */
export declare const Input: DefineComponent<InputProps>
