import { JOB_TAB_KEYS, TAB_LABELS, type JobTabKey } from './tabs'

interface JobViewTabsProps {
  activeTab: JobTabKey
  pricingMethodology: string | null
  onChangeTab: (tab: JobTabKey) => void
}

/**
 * The job detail tab bar. Time & materials jobs have no quote, so that tab
 * disappears rather than rendering empty.
 */
export function JobViewTabs({ activeTab, pricingMethodology, onChangeTab }: JobViewTabsProps) {
  const tabs =
    pricingMethodology === 'time_materials'
      ? JOB_TAB_KEYS.filter((tab) => tab !== 'quote')
      : JOB_TAB_KEYS

  return (
    <nav className="flex space-x-1 overflow-x-auto border-b border-gray-200 px-4">
      {tabs.map((tab) => (
        <button
          key={tab}
          type="button"
          data-automation-id={`JobViewTabs-${tab}`}
          className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
            activeTab === tab
              ? 'border-blue-600 text-blue-600'
              : 'border-transparent text-gray-600 hover:text-gray-900'
          }`}
          onClick={() => onChangeTab(tab)}
        >
          {TAB_LABELS[tab]}
        </button>
      ))}
    </nav>
  )
}
