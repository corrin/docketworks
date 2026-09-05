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
import { formatDate } from '@/lib/format'
import { PickupAddressSelector } from './PickupAddressSelector'
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

interface PoSummaryCardDetailProps {
  mode: 'detail'
  po: PurchaseOrderDetail
  patchHeader: (fields: PoHeaderPatch, display?: Partial<PurchaseOrderDetail>) => void
}

type PoSummaryCardProps = PoSummaryCardCreateProps | PoSummaryCardDetailProps

/**
 * The PO header card, in create mode (supplier lookup + reference, values
 * owned by the create page) or detail mode (autosaving edits through the
 * single PO PATCH). One component rather than two siblings so the
 * `PoSummaryCard-*` automation ids live in exactly one place.
 */
export function PoSummaryCard(props: PoSummaryCardProps) {
  return (
    <div className="space-y-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <h2 className="text-sm font-semibold text-gray-700">Purchase Order Details</h2>
      {props.mode === 'create' ? <CreateFields {...props} /> : <DetailFields {...props} />}
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
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <div>
        <span className="mb-1 block text-sm font-medium text-gray-700">PO Number</span>
        <p className="px-1 py-2 text-sm font-semibold text-gray-900">{po.po_number}</p>
      </div>
      <div>
        <span className="mb-1 block text-sm font-medium text-gray-700">Supplier</span>
        <p className="px-1 py-2 text-sm text-gray-900">{po.supplier || '—'}</p>
      </div>
      <div>
        <span className="mb-1 block text-sm font-medium text-gray-700">Order Date</span>
        <p className="px-1 py-2 text-sm text-gray-900">{formatDate(po.order_date)}</p>
      </div>
      <div>
        {/* An input, not a span: the E2E contract reads this via inputValue(). */}
        <label htmlFor="po-created-by" className="mb-1 block text-sm font-medium text-gray-700">
          Created By
        </label>
        <input
          id="po-created-by"
          type="text"
          readOnly
          value={po.created_by_name}
          data-automation-id="PoSummaryCard-created-by"
          className="w-full rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-gray-700"
        />
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
      {po.supplier_id && (
        <div className="sm:col-span-2">
          <PickupAddressSelector
            supplier={{ id: po.supplier_id, name: po.supplier }}
            selected={po.pickup_address}
            onChange={(address) =>
              patchHeader({ pickup_address_id: address?.id ?? null }, { pickup_address: address })
            }
          />
        </div>
      )}
      <div>
        <span className="mb-1 block text-sm font-medium text-gray-700">Status</span>
        <Select
          value={po.status}
          onValueChange={(value) => patchHeader({ status: toPoStatus(value) })}
        >
          <SelectTrigger data-automation-id="PoSummaryCard-status-trigger" className="w-full">
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
    </div>
  )
}
