import { useTranslation } from 'react-i18next'

import { QueryState } from '@/features/shared/QueryState'
import { EntryGridSection } from '@/features/shared/EntryGridSection'
import { PoLinesTable } from './PoLinesTable'
import { PoDetailHeader, PoOrderValue, PoSummaryCard } from './PoSummaryCard'
import { PoHistorySection } from './PoHistorySection'
import { usePoLines } from './usePoLines'

interface PoDetailPageProps {
  poId: string
}

export function PoDetailPage({ poId }: PoDetailPageProps) {
  const { t } = useTranslation('purchasing')
  const { poQuery, patchHeader, patchLine, createLine, deleteLine } = usePoLines(poId)
  const po = poQuery.data

  return (
    <div className="min-w-0">
      <QueryState
        isPending={poQuery.isPending}
        // No fabricated empty page: a failed FIRST load must not read as a
        // PO with no lines. Background refetch errors keep the working
        // page — the write paths toast their own failures.
        isError={poQuery.isError && po === undefined}
        loadingLabel={t('poDetail.loading')}
        errorLabel={t('poDetail.loadFailed')}
      >
        {po && (
          <>
            <PoDetailHeader po={po} patchHeader={patchHeader} />
            <main className="min-w-0 space-y-4 p-4">
              <PoSummaryCard mode="detail" po={po} patchHeader={patchHeader} />
              <EntryGridSection
                title={
                  <>
                    {t('poDetail.lineItems')}{' '}
                    <span className="ml-2 text-xs font-normal text-slate-500">
                      {t('poDetail.lineCount', { count: po.lines.length })}
                    </span>
                  </>
                }
                actions={<PoOrderValue lines={po.lines} />}
              >
                <PoLinesTable
                  lines={po.lines}
                  patchLine={patchLine}
                  deleteLine={deleteLine}
                  createLine={createLine}
                />
              </EntryGridSection>
              <PoHistorySection key={poId} poId={poId} />
            </main>
          </>
        )}
      </QueryState>
    </div>
  )
}
