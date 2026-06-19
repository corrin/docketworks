import type { ToasterProps } from 'vue-sonner'

/**
 * Toaster — the toast host/region (wraps vue-sonner's <Toaster>).
 * Mount ONCE near the app root. Renders nothing until onMounted (client only).
 * Themed via CSS vars: --normal-bg=var(--popover),
 * --normal-text=var(--popover-foreground), --normal-border=var(--border).
 *
 * Props are vue-sonner's ToasterProps, forwarded verbatim, including:
 *  - position?: 'top-left'|'top-center'|'top-right'|'bottom-left'|'bottom-center'|'bottom-right'
 *  - richColors?: boolean
 *  - expand?: boolean
 *  - duration?: number
 *  - closeButton?: boolean
 *  - theme?: 'light' | 'dark' | 'system'
 *  - visibleToasts?: number
 *  - offset?: string | number
 */
export type { ToasterProps }
export declare const Toaster: import('vue').DefineComponent<ToasterProps>

/**
 * toast() — imperative API to fire toasts.
 * NOT re-exported by '@/components/ui/sonner'; import from 'vue-sonner':
 *   import { toast } from 'vue-sonner'
 *
 *   toast('Saved')
 *   toast.success('Job created')
 *   toast.error('Could not save')
 *   toast.warning('Check the date')
 *   toast.info('Synced with Xero')
 *   toast.message('Title', { description: '...' })
 *   toast.promise(p, { loading, success, error })
 *   toast.loading('Working…')
 *   toast.dismiss(id?)
 */
export declare const toast: typeof import('vue-sonner').toast
