import { useRef } from 'react'

export interface TabBarItem<TKey extends string> {
  key: TKey
  label: string
}

interface TabBarProps<TKey extends string> {
  tabs: readonly TabBarItem<TKey>[]
  activeKey: TKey
  onChange: (key: TKey) => void
  /** Automation ids and DOM ids are `${idPrefix}-${key}`, so each caller keeps
      the ids its specs already drive. */
  idPrefix: string
  /** The id of the region this bar switches. The caller puts it on one element
      carrying `role="tabpanel"`; content swapping inside it is the point. */
  panelId: string
  /** The nav's own spacing — callers sit this in a page header, a filter
      row or a card header, and own that difference. */
  className?: string
}

/**
 * The one underline tab bar. Generalised out of JobViewTabs rather than
 * copied a fourth time (ADR 0039).
 *
 * Opus: Plain buttons rather than a Radix Tabs primitive — components/ui
 * carries none, and the W3C APG contract below is the whole of what one would
 * bring. Declaring the roles obliges us to the rest of that pattern: a
 * `tablist` whose arrow keys do nothing is worse than unlabelled buttons,
 * because assistive tech tells the user to arrow through it. So the roles,
 * roving tabindex, Arrow/Home/End and the panel association ship together or
 * not at all — CompanyDetailPage carried the roles alone before this component
 * existed, and that gap is what this fixes rather than propagates.
 *
 * Each label renders exactly once, deliberately: PhoneCallsPage.test.tsx
 * counts findAllByText('Recent Calls') === 2, one for the tab and one for the
 * queue heading, so a hidden duplicate or a title= echo here fails it.
 */
export function TabBar<TKey extends string>({
  tabs,
  activeKey,
  onChange,
  idPrefix,
  panelId,
  className,
}: TabBarProps<TKey>) {
  const navRef = useRef<HTMLElement>(null)

  const focusTab = (key: TKey): void => {
    onChange(key)
    // The button already exists; only its tabIndex changes on re-render, and
    // focus() works on a tabIndex=-1 element, so this needs no effect.
    navRef.current
      ?.querySelector<HTMLButtonElement>(`#${CSS.escape(`${idPrefix}-${key}`)}`)
      ?.focus()
  }

  const onKeyDown = (event: React.KeyboardEvent<HTMLElement>): void => {
    const index = tabs.findIndex((tab) => tab.key === activeKey)
    const nextIndex: Record<string, number> = {
      ArrowLeft: (index - 1 + tabs.length) % tabs.length,
      ArrowRight: (index + 1) % tabs.length,
      Home: 0,
      End: tabs.length - 1,
    }
    const target = nextIndex[event.key]
    if (target === undefined) return
    const next = tabs[target]
    // Unreachable for a non-empty tabs list; the guard is what lets the index
    // stay a plain number under strict null checks.
    if (next === undefined) return
    event.preventDefault()
    focusTab(next.key)
  }

  return (
    <nav
      ref={navRef}
      role="tablist"
      className={`flex space-x-1 border-b border-gray-200 ${className ?? ''}`}
      onKeyDown={onKeyDown}
    >
      {tabs.map((tab) => (
        <button
          key={tab.key}
          id={`${idPrefix}-${tab.key}`}
          type="button"
          role="tab"
          aria-selected={activeKey === tab.key}
          aria-controls={panelId}
          // Roving tabindex: the tab strip is one stop in the page's Tab order
          // and the arrow keys move within it (W3C APG Tabs).
          tabIndex={activeKey === tab.key ? 0 : -1}
          data-automation-id={`${idPrefix}-${tab.key}`}
          className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
            activeKey === tab.key
              ? 'border-blue-600 text-blue-600'
              : 'border-transparent text-gray-600 hover:text-gray-900'
          }`}
          onClick={() => onChange(tab.key)}
        >
          {tab.label}
        </button>
      ))}
    </nav>
  )
}
