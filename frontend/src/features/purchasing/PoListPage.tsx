import { keepPreviousData, useInfiniteQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { listPurchaseOrdersInfiniteOptions } from '@/api'
import { Button } from '@/components/ui/button'
import { ListTable } from '@/features/shared/ListTable'
import { LoadMoreSentinel } from '@/features/shared/LoadMoreSentinel'
import { nextPageParam } from '@/features/shared/nextPageParam'
import { SEARCH_DEBOUNCE_MS, useDebouncedValue } from '@/features/shared/useDebouncedValue'
import { formatDate } from '@/lib/format'
import { PO_STATUS_DISPLAY, poStatusLabel } from './status'
import { poListJobsLabel } from './lines'
import { SearchInput } from '@/features/shared/SearchInput'

/**
 * Purchase orders, searched and paged by the server.
 *
 * Opus: search reaches the API rather than filtering the loaded rows. Production
 * holds 990 orders over 2,315 lines, so a client-side filter would only search
 * the page it happens to hold — and the unpaginated list this replaced sent all
 * of them on every visit (ADR 0054).
 */
export function PoListPage() {
  const { t } = useTranslation('purchasing')
  const navigate = useNavigate()
  const [searchInput, setSearchInput] = useState('')
  const query = useDebouncedValue(searchInput, SEARCH_DEBOUNCE_MS)

  const purchaseOrders = useInfiniteQuery({
    ...listPurchaseOrdersInfiniteOptions({ query: { q: query } }),
    initialPageParam: 1,
    getNextPageParam: nextPageParam,
    // A refetch of an infinite query re-requests every loaded page in series,
    // so a window-focus refetch deep in the list is many requests for nothing.
    refetchOnWindowFocus: false,
    // Search changes the query key; without placeholder data every keystroke
    // would unmount the table and re-flash the loading text.
    placeholderData: keepPreviousData,
  })
  const rows = purchaseOrders.data?.pages.flatMap((page) => page.results)
  const lastPage = purchaseOrders.data?.pages.at(-1)

  return (
    <div className="min-h-screen p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-900">{t('poList.title')}</h1>
        <Button
          data-automation-id="PurchaseOrderView-new-po"
          onClick={() => void navigate({ to: '/purchasing/po/create' })}
        >
          {t('poList.newPo')}
        </Button>
      </div>

      <div className="mt-4">
        <SearchInput
          value={searchInput}
          onChange={setSearchInput}
          placeholder={t('poList.searchPlaceholder')}
          automationId="PurchaseOrderView-search"
          label={t('poList.searchLabel')}
        />
      </div>

      <ListTable
        isPending={purchaseOrders.isPending}
        // A failed FIRST load is the error state; an errored background refetch
        // keeps the keepPreviousData table on screen instead of unmounting it.
        isError={purchaseOrders.isError && purchaseOrders.data === undefined}
        onRetry={() => void purchaseOrders.refetch()}
        loadingLabel={t('poList.loading')}
        errorLabel={t('poList.loadFailed')}
        rows={rows}
        emptyLabel={t('poList.empty')}
        head={
          <tr className="border-b border-gray-200 text-left text-gray-500">
            <th scope="col" className="px-3 py-2">
              {t('poList.header.poNumber')}
            </th>
            <th scope="col" className="px-3 py-2" title={t('poList.titles.jobs')}>
              {t('poList.header.jobs')}
            </th>
            <th scope="col" className="px-3 py-2">
              {t('poList.header.supplier')}
            </th>
            <th scope="col" className="px-3 py-2" title={t('poList.titles.orderDate')}>
              {t('poList.header.orderDate')}
            </th>
            <th scope="col" className="px-3 py-2" title={t('poList.titles.status')}>
              {t('poList.header.status')}
            </th>
            <th scope="col" className="px-3 py-2" title={t('poList.titles.createdBy')}>
              {t('poList.header.createdBy')}
            </th>
          </tr>
        }
        renderRow={(po) => (
          <tr
            key={po.id}
            data-automation-id={`PurchaseOrderView-row-${po.id}`}
            className="cursor-pointer border-b border-gray-100 hover:bg-blue-50"
            onClick={() => {
              void navigate({ to: '/purchasing/po/$poId', params: { poId: po.id } })
            }}
          >
            <td className="px-3 py-2 font-medium text-gray-900">
              {/* A real link so keyboard users can open the detail page;
                  the row onClick is the mouse-only whole-row affordance
                  (same pattern as CompaniesListPage). */}
              <Link
                to="/purchasing/po/$poId"
                params={{ poId: po.id }}
                className="hover:underline"
                onClick={(event) => event.stopPropagation()}
              >
                {po.po_number}
              </Link>
            </td>
            <td
              className="px-3 py-2"
              data-automation-id={`PurchaseOrderView-jobs-${po.id}`}
              title={po.jobs
                .map((job) => t('poList.jobTitle', { number: job.job_number, name: job.name }))
                .join(', ')}
            >
              {poListJobsLabel(po.jobs)}
            </td>
            <td className="px-3 py-2">{po.supplier}</td>
            <td className="px-3 py-2">{formatDate(po.order_date)}</td>
            <td className="px-3 py-2">
              <span
                className={`rounded-full px-2 py-0.5 text-xs font-medium ${PO_STATUS_DISPLAY[po.status].className}`}
              >
                {poStatusLabel(po.status)}
              </span>
            </td>
            <td className="px-3 py-2" data-automation-id={`PurchaseOrderView-created-by-${po.id}`}>
              {po.created_by_name || t('poList.noCreator')}
            </td>
          </tr>
        )}
      />

      {rows !== undefined && lastPage !== undefined && (
        <LoadMoreSentinel
          automationId="PurchaseOrderView-load-more"
          noun={t('poList.noun')}
          shown={rows.length}
          total={lastPage.count}
          hasNextPage={purchaseOrders.hasNextPage}
          isFetchingNextPage={purchaseOrders.isFetchingNextPage}
          isFetchNextPageError={purchaseOrders.isFetchNextPageError}
          onLoadMore={() => void purchaseOrders.fetchNextPage()}
        />
      )}
    </div>
  )
}
