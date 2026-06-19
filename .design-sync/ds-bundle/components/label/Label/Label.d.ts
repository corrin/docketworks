// Label — accessible form label. shadcn-vue wrapper over reka-ui Label.
// Source: frontend/src/components/ui/label/Label.vue

import type { DefineComponent } from 'vue'
import type { LabelProps as RekaLabelProps } from 'reka-ui'

export interface LabelProps extends /* reka-ui */ RekaLabelProps {
  /** Associates the label with a control by id (native `for`). */
  for?: string
  /** Render as a different element / child (reka-ui asChild). */
  as?: RekaLabelProps['as']
  asChild?: boolean
  /** Extra classes merged via cn(). */
  class?: string
}

/**
 * @slot default — label text/content (may include icons; layout is flex gap-2).
 */
export declare const Label: DefineComponent<LabelProps>
