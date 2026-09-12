import type { CompanySearchResult, PurchaseOrderDetail, SupplierPickupAddressOut } from '@/api'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { CompanyLookup } from '@/features/shared/company'
import { orNull } from '@/features/shared/nullableText'
import { useAutosaveField } from '@/features/shared/useAutosaveField'
import { INPUT_CLASS } from '@/components/ui/field'
import { formatCurrency, formatDate } from '@/lib/format'
import { poOrderValue } from './lines'
import { PickupAddressSelector } from './PickupAddressSelector'
import { PoDocumentActions } from './PoDocumentActions'
import { PO_STATUS_OPTIONS, toPoStatus } from './status'
import type { PoHeaderPatch } from './usePoLines'

interface PoSummaryCardCreateProps {
  mode: 'create'
  supplier: CompanySearchResult | null
  onSelectSupplier: (company: CompanySearchResult | null) => void
  reference: string
  onReferenceChange: (value: string) => void
  /** undefined: untouched, the backend picks the primary; null: cleared, none. */
  pickupAddress: SupplierPickupAddressOut | null | undefined
  onSelectPickupAddress: (address: SupplierPickupAddressOut | null) => void
  /** A new supplier starts untouched: its addresses are its own. */
  onResetPickupAddress: () => void
}

interface PoDetailProps {
  po: PurchaseOrderDetail
  patchHeader: (fields: PoHeaderPatch, display?: Partial<PurchaseOrderDetail>) => void
}

type PoSummaryCardDetailProps = PoDetailProps & { mode: 'detail' }

type PoSummaryCardProps = PoSummaryCardCreateProps | PoSummaryCardDetailProps

export function PoSummaryCard(props: PoSummaryCardProps) {
  if (props.mode === 'detail') return <DetailFields {...props} />
  return (
    <div className="space-y-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <h2 className="text-sm font-semibold text-gray-700">Purchase Order Details</h2>
      <CreateFields {...props} />
    </div>
  )
}

export function PoDetailHeader({ po, patchHeader }: PoDetailProps) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-200 p-4">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-bold text-gray-900">Purchase Order {po.po_number}</h1>
          <Select
            value={po.status}
            onValueChange={(value) => patchHeader({ status: toPoStatus(value) })}
          >
            <SelectTrigger
              aria-label="Purchase order status"
              data-automation-id="PoSummaryCard-status-trigger"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PO_STATUS_OPTIONS.map((option) => (
                <SelectItem
                  key={option.value}
                  value={option.value}
                  data-automation-id={`PoSummaryCard-status-${option.value}`}
                >
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <p className="mt-2 text-xs text-slate-500">
          Order date: {formatDate(po.order_date)} · Created by:{' '}
          <span data-automation-id="PoSummaryCard-created-by">{po.created_by_name}</span>
        </p>
      </div>
      <PoDocumentActions po={po} />
    </header>
  )
}

export function PoOrderValue({ lines }: Pick<PurchaseOrderDetail, 'lines'>) {
  const orderValue = poOrderValue(lines)
  return (
    <div className="text-right">
      <span className="mr-2 text-sm text-slate-500">
        {orderValue.unresolvedCount === 0 ? 'Total' : 'Known subtotal'}
      </span>
      <span
        className="font-semibold text-gray-900 tabular-nums"
        data-automation-id="PoSummaryCard-order-value"
      >
        {formatCurrency(orderValue.knownSubtotal)}
      </span>
      {orderValue.unresolvedCount > 0 && (
        <p className="text-xs text-amber-700">
          {orderValue.unresolvedCount} {orderValue.unresolvedCount === 1 ? 'line' : 'lines'}{' '}
          unpriced
        </p>
      )}
    </div>
  )
}

function ReferenceLabel() {
  return (
    <label htmlFor="po-reference" className="mb-1 block text-sm font-medium text-gray-700">
      Reference
    </label>
  )
}

function CreateFields({
  supplier,
  onSelectSupplier,
  reference,
  onReferenceChange,
  pickupAddress,
  onSelectPickupAddress,
  onResetPickupAddress,
}: PoSummaryCardCreateProps) {
  return (
    <div className="space-y-4">
      <CompanyLookup
        id="po-supplier"
        label="Supplier"
        selectedCompany={supplier}
        onSelectCompany={(company) => {
          onSelectSupplier(company)
          onResetPickupAddress()
        }}
        mode="supplier"
      />
      {supplier && (
        <PickupAddressSelector
          supplier={{ id: supplier.id, name: supplier.name }}
          selected={pickupAddress ?? null}
          onChange={onSelectPickupAddress}
          placeholder={
            pickupAddress === undefined
              ? "The supplier's primary address, unless chosen here"
              : 'No pickup address'
          }
        />
      )}
      <div>
        <ReferenceLabel />
        <input
          id="po-reference"
          type="text"
          value={reference}
          autoComplete="off"
          data-automation-id="PoSummaryCard-reference"
          className={INPUT_CLASS}
          onChange={(event) => onReferenceChange(event.target.value)}
        />
      </div>
    </div>
  )
}

function DetailFields({ po, patchHeader }: PoSummaryCardDetailProps) {
  const referenceField = useAutosaveField(po.reference ?? '', (value) =>
    patchHeader({ reference: orNull(value) }),
  )

  return (
    <div className="grid min-w-0 grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_160px_minmax(0,1.7fr)]">
      <div>
        {/* Read-only even while draft, unlike v1. CompanyLookup is controlled by
            a whole CompanySearchResult — it renders the supplier's email and
            Xero badge — and the PO detail carries only the name, id and
            supplier_has_xero_id. Seeding it means fetching the company, which
            is a change to make deliberately rather than as a side effect of
            this card. Tracked in docs/rewrite-status.md. */}
        <span className="mb-1 block text-sm font-medium text-gray-700">Supplier</span>
        <p className="py-2 text-sm break-words text-gray-900">{po.supplier || '—'}</p>
      </div>
      <div>
        <ReferenceLabel />
        <input
          id="po-reference"
          type="text"
          value={referenceField.value}
          autoComplete="off"
          data-automation-id="PoSummaryCard-reference"
          className={INPUT_CLASS}
          onChange={(event) => referenceField.onChange(event.target.value)}
          onFocus={referenceField.onFocus}
          onBlur={referenceField.onBlur}
        />
      </div>
      <div>
        <label
          htmlFor="po-expected-delivery"
          className="mb-1 block text-sm font-medium text-gray-700"
        >
          Expected Delivery
        </label>
        <input
          id="po-expected-delivery"
          type="date"
          value={po.expected_delivery ?? ''}
          data-automation-id="PoSummaryCard-expected-delivery"
          className={INPUT_CLASS}
          onChange={(event) =>
            patchHeader({
              expected_delivery: event.target.value === '' ? null : event.target.value,
            })
          }
        />
      </div>
      {po.supplier_id && (
        <div className="min-w-0">
          <PickupAddressSelector
            supplier={{ id: po.supplier_id, name: po.supplier }}
            selected={po.pickup_address}
            onChange={(address) =>
              patchHeader({ pickup_address_id: address?.id ?? null }, { pickup_address: address })
            }
          />
        </div>
      )}
    </div>
  )
}
