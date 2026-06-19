import type { HTMLAttributes } from 'vue'
import type {
  TabsRootProps,
  TabsRootEmits,
  TabsListProps as RekaTabsListProps,
  TabsTriggerProps as RekaTabsTriggerProps,
  TabsContentProps as RekaTabsContentProps,
} from 'reka-ui'

/**
 * Tabs — wraps reka-ui TabsRoot. Switches between panels.
 * Controlled/uncontrolled via `modelValue` / `defaultValue`.
 *
 * @slot default — TabsList + TabsContent(s)
 */
export interface TabsProps extends TabsRootProps {
  class?: HTMLAttributes['class']
}
export type TabsEmits = TabsRootEmits

/** Container for the triggers (reka-ui TabsList). @slot default — TabsTrigger(s) */
export interface TabsListProps extends RekaTabsListProps {
  class?: HTMLAttributes['class']
}

/** A single tab button (reka-ui TabsTrigger). `value` ties it to a TabsContent. @slot default — label */
export interface TabsTriggerProps extends RekaTabsTriggerProps {
  class?: HTMLAttributes['class']
}

/** A tab panel (reka-ui TabsContent). Shown when its `value` is active. @slot default — panel content */
export interface TabsContentProps extends RekaTabsContentProps {
  class?: HTMLAttributes['class']
}

export declare const Tabs: import('vue').DefineComponent<TabsProps>
export declare const TabsList: import('vue').DefineComponent<TabsListProps>
export declare const TabsTrigger: import('vue').DefineComponent<TabsTriggerProps>
export declare const TabsContent: import('vue').DefineComponent<TabsContentProps>
