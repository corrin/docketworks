import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { jobJobsLabourRatesListOptions, purchasingStockSearchRetrieveOptions } from '@/api'
import type { JobLabourRateOut, StockItem } from '@/api'
import { Button } from '@/components/ui/button'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'

const STOCK_PAGE_SIZE = 50

/** The trigger label, resolved against the picker's own fetched data — a
    bound stock item may only be known to this component's query. */
type ItemLabel =
  | string
  | ((
      stockById: ReadonlyMap<string, StockItem>,
      labourRates: readonly JobLabourRateOut[],
    ) => string)

interface ItemSelectProps {
  /** Omit where labour is never a valid pick for this grid — also disables
      the labour-rates query, since no job means no rates to fetch. */
  jobId?: string
  /** Must resolve to 'Select Item' ONLY while nothing is bound — the E2E
      repair loop counts buttons by that exact name. */
  label: ItemLabel
  /** Wrapper automation id — each grid supplies its own selector family. */
  wrapperAutomationId: string
  disabled: boolean
  /** The actual set books labour through timesheets, never through a pick. */
  allowLabour?: boolean
  /** Render only the resolved label, no picker — for a row whose item this
      component must not let the user rebind. The wrapper automation id
      stays identical either way: callers bind to it regardless of mode. */
  textOnly?: boolean
  onPickStock: (stock: StockItem) => void
  onPickLabour?: (rate: JobLabourRateOut, allRates: readonly JobLabourRateOut[]) => void
}

/**
 * The item picker shared by every grid that binds stock (and optionally
 * labour) to a row: labour subtypes pinned first, then stock. The
 * `ItemSelect-option-*` ids and the search placeholder are wire contract.
 *
 * Server-side stock search (paginated at 50): the unpaginated stock list can
 * exceed the E2E wire-size guard, and queries under 3 characters list
 * everything, so an empty search still shows a first page.
 */
export function ItemSelect({
  jobId,
  label,
  wrapperAutomationId,
  disabled,
  allowLabour = true,
  textOnly = false,
  onPickStock,
  onPickLabour,
}: ItemSelectProps) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')

  const labourQuery = useQuery({
    // The '' placeholder never reaches the wire: the query is disabled
    // whenever jobId is absent. Gated on jobId alone, NOT on allowLabour —
    // textOnly labour labels need the rate names even where picking labour
    // is forbidden (the actual tab's read-only timesheet lines).
    ...jobJobsLabourRatesListOptions({ path: { job_id: jobId ?? '' } }),
    enabled: jobId !== undefined,
  })
  const stockQuery = useQuery({
    ...purchasingStockSearchRetrieveOptions({
      query: { q: search, page_size: STOCK_PAGE_SIZE },
    }),
    enabled: open,
  })

  const labourRates = labourQuery.data ?? []
  const stockItems = stockQuery.data?.results ?? []
  const stockById = new Map(stockItems.map((stock) => [stock.id, stock]))
  const lowered = search.trim().toLowerCase()
  const visibleLabour = !allowLabour
    ? []
    : lowered
      ? labourRates.filter((rate) => rate.labour_subtype_name.toLowerCase().includes(lowered))
      : labourRates

  const resolvedLabel = typeof label === 'string' ? label : label(stockById, labourRates)

  if (textOnly) {
    return (
      <span data-automation-id={wrapperAutomationId}>
        <span className="text-sm font-medium text-blue-700">{resolvedLabel}</span>
      </span>
    )
  }

  const pick = (action: () => void) => {
    action()
    setOpen(false)
    setSearch('')
  }

  return (
    <span data-automation-id={wrapperAutomationId}>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button variant="outline" size="sm" disabled={disabled} className="max-w-40 truncate">
            {resolvedLabel}
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-80 p-0" align="start">
          {/* The server filters stock; Command must not re-filter or labour
              options would vanish whenever the query matches only stock. */}
          <Command shouldFilter={false}>
            <CommandInput
              // The E2E contract asserts the search field is focused the
              // moment the popover opens; Radix's focus scope lands on the
              // content wrapper, not the input, without this.
              autoFocus
              placeholder="Search items by description, code, or type..."
              value={search}
              onValueChange={setSearch}
            />
            <CommandList>
              <CommandEmpty>
                {/* An error must not read as an empty catalogue. */}
                {stockQuery.isError
                  ? 'Could not load stock items.'
                  : stockQuery.isPending
                    ? 'Loading items…'
                    : 'No items found.'}
              </CommandEmpty>
              {labourQuery.isError && (
                <p className="px-3 py-2 text-xs text-red-700">Could not load labour rates.</p>
              )}
              {visibleLabour.length > 0 && (
                <CommandGroup heading="Labour">
                  {visibleLabour.map((rate) => (
                    <CommandItem
                      key={rate.id}
                      value={`labour-${rate.labour_subtype}`}
                      data-automation-id={`ItemSelect-option-labour-${rate.labour_subtype}`}
                      onSelect={() => pick(() => onPickLabour?.(rate, labourRates))}
                    >
                      <span className="font-medium">{rate.labour_subtype_name}</span>
                      <span className="ml-auto text-xs text-slate-500">
                        {rate.charge_out_rate}/hr
                      </span>
                    </CommandItem>
                  ))}
                </CommandGroup>
              )}
              {stockItems.length > 0 && (
                <CommandGroup heading="Stock">
                  {stockItems.map((stock) => (
                    <CommandItem
                      key={stock.id}
                      value={stock.id}
                      data-automation-id={`ItemSelect-option-${stock.item_code ?? stock.id}`}
                      onSelect={() => pick(() => onPickStock(stock))}
                    >
                      <span className="truncate">{stock.description}</span>
                      {stock.item_code && (
                        <span className="ml-auto text-xs text-slate-500">{stock.item_code}</span>
                      )}
                    </CommandItem>
                  ))}
                </CommandGroup>
              )}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </span>
  )
}
