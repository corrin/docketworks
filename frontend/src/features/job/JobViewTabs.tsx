import { TabBar } from '@/features/shared/TabBar'

import { JOB_TAB_KEYS, TAB_LABELS, type JobTabKey } from './tabs'

interface JobViewTabsProps {
  activeTab: JobTabKey
  pricingMethodology: string | null
  onChangeTab: (tab: JobTabKey) => void
}

/**
 * The job detail tab bar. Time & materials jobs have no quote, so that tab
 * disappears rather than rendering empty.
 *
 * Opus: Kept as its own component over calling TabBar directly from
 * JobDetailPage — the quote-tab rule is job pricing policy, not tab-bar
 * mechanics, and it is the only thing this file still owns.
 */
export function JobViewTabs({ activeTab, pricingMethodology, onChangeTab }: JobViewTabsProps) {
  const tabs = (
    pricingMethodology === 'time_materials'
      ? JOB_TAB_KEYS.filter((tab) => tab !== 'quote')
      : JOB_TAB_KEYS
  ).map((tab) => ({ key: tab, label: TAB_LABELS[tab] }))

  return (
    <TabBar
      tabs={tabs}
      activeKey={activeTab}
      onChange={onChangeTab}
      idPrefix="JobViewTabs"
      className="overflow-x-auto px-4"
    />
  )
}
