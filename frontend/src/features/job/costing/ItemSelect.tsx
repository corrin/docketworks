import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { jobJobsLabourRatesListOptions, purchasingStockSearchRetrieveOptions } from '@/api'
import type { CostLineOut, JobLabourRateOut, StockItem } from '@/api'
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
import { itemLabel } from './calc'

const STOCK_PAGE_SIZE = 50

interface ItemSelectProps {
  jobId: string
  line: CostLineOut
  rowIndex: number
  disabled: boolean
  onPickStock: (stock: StockItem) => void
  onPickLabour: (rate: JobLabourRateOut) => void
}

/**
 * The item picker: labour subtypes pinned first, then stock. The trigger's
 * accessible name is 'Select Item' ONLY while nothing is bound — the E2E
 * repair loop counts buttons by that exact name, so a bound row must stop
 * matching or the loop never terminates.
 *
 * Server-side stock search (paginated at 50): the unpaginated stock list can
 * exceed the E2E wire-size guard, and queries under 3 characters list
 * everything, so an empty search still shows a first page.
 */
export function ItemSelect({
  jobId,
  line,
  rowIndex,
  disabled,
  onPickStock,
  onPickLabour,
}: ItemSelectProps) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')

  const labourQuery = useQuery({
    ...jobJobsLabourRatesListOptions({ path: { job_id: jobId } }),
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
  const visibleLabour = lowered
    ? labourRates.filter((rate) => rate.labour_subtype_name.toLowerCase().includes(lowered))
    : labourRates

  const label = itemLabel(line, stockById, labourRates)

  const pick = (action: () => void) => {
    action()
    setOpen(false)
    setSearch('')
  }

  return (
    <span data-automation-id={`SmartCostLinesTable-item-${rowIndex}`}>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button variant="outline" size="sm" disabled={disabled} className="max-w-40 truncate">
            {label}
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-80 p-0" align="start">
          {/* The server filters stock; Command must not re-filter or labour
              options would vanish whenever the query matches only stock. */}
          <Command shouldFilter={false}>
            <CommandInput
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
                      onSelect={() => pick(() => onPickLabour(rate))}
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
