export interface TabBarItem<TKey extends string> {
  key: TKey
  label: string
}

interface TabBarProps<TKey extends string> {
  tabs: readonly TabBarItem<TKey>[]
  activeKey: TKey
  onChange: (key: TKey) => void
  /** Automation ids are `${idPrefix}-${key}`, so each caller keeps the ids
      its specs already drive. */
  idPrefix: string
  /** The nav's own spacing — callers sit this in a page header, a filter
      row or a card header, and own that difference. */
  className?: string
}

/**
 * The one underline tab bar. Generalised out of JobViewTabs rather than
 * copied a fourth time (ADR 0039).
 *
 * Opus: Plain buttons rather than a Radix Tabs primitive — components/ui
 * carries none, and the ARIA below is the whole of what one would add here.
 * The roles come from CompanyDetailPage, the only one of the three original
 * bars that had them: adopting them broke nothing (its two getByRole('tab')
 * specs keep passing) and gave the other bars an accessible tab list.
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
  className,
}: TabBarProps<TKey>) {
  return (
    <nav role="tablist" className={`flex space-x-1 border-b border-gray-200 ${className ?? ''}`}>
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          role="tab"
          aria-selected={activeKey === tab.key}
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
