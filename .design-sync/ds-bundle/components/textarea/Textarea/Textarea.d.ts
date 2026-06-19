// Textarea — multi-line text field. shadcn-vue wrapper over a native <textarea>.
// Source: frontend/src/components/ui/textarea/Textarea.vue

import type { DefineComponent } from 'vue'

export interface TextareaProps {
  /** Extra classes merged via cn(). */
  class?: string
  /** Initial value when uncontrolled. */
  defaultValue?: string | number
  /** v-model value. */
  modelValue?: string | number
  // Native <textarea> attributes (placeholder, disabled, rows, readonly,
  // aria-invalid, name, id, etc.) pass through via fallthrough attrs.
}

export interface TextareaEmits {
  (e: 'update:modelValue', payload: string | number): void
}

/**
 * @slot (none) — renders a native <textarea data-slot="textarea">.
 */
export declare const Textarea: DefineComponent<TextareaProps>
