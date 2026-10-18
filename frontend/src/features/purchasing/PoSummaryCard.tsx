import { useTranslation } from 'react-i18next'

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
import { PO_STATUS_ORDER, poStatusLabel, poStatusTitle, toPoStatus } from './status'
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
  const { t } = useTranslation('purchasing')
  if (props.mode === 'detail') return <DetailFields {...props} />
  return (
    <div className="space-y-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <h2 className="text-sm font-semibold text-gray-700">{t('poSummary.detailsHeading')}</h2>
      <CreateFields {...props} />
    </div>
  )
}

export function PoDetailHeader({ po, patchHeader }: PoDetailProps) {
  const { t } = useTranslation('purchasing')
  return (
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-200 p-4">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-bold text-gray-900">
            {t('poSummary.title', { number: po.po_number })}
          </h1>
          <Select
            value={po.status}
            onValueChange={(value) => patchHeader({ status: toPoStatus(value) })}
          >
            <SelectTrigger
              aria-label={t('poSummary.statusLabel')}
              title={t('poSummary.statusLabelTitle')}
              data-automation-id="PoSummaryCard-status-trigger"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PO_STATUS_ORDER.map((status) => (
                <SelectItem
                  key={status}
                  value={status}
                  title={poStatusTitle(status)}
                  data-automation-id={`PoSummaryCard-status-${status}`}
                >
                  {poStatusLabel(status)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <p className="mt-2 text-xs text-slate-500">
          {t('poSummary.orderDate', { date: formatDate(po.order_date) })}{' '}
          <span data-automation-id="PoSummaryCard-created-by">{po.created_by_name}</span>
        </p>
      </div>
      <PoDocumentActions po={po} />
    </header>
  )
}

export function PoOrderValue({ lines }: Pick<PurchaseOrderDetail, 'lines'>) {
  const { t } = useTranslation('purchasing')
  const orderValue = poOrderValue(lines)
  return (
    <div className="text-right" title={t('poSummary.totalTitle')}>
      <span className="mr-2 text-sm text-slate-500">
        {orderValue.unresolvedCount === 0 ? t('poSummary.total') : t('poSummary.knownSubtotal')}
      </span>
      <span
        className="font-semibold text-gray-900 tabular-nums"
        data-automation-id="PoSummaryCard-order-value"
      >
        {formatCurrency(orderValue.knownSubtotal)}
      </span>
      {orderValue.unresolvedCount > 0 && (
        <p className="text-xs text-amber-700" title={t('poSummary.unpricedTitle')}>
          {t('poSummary.unpriced', { count: orderValue.unresolvedCount })}
        </p>
      )}
    </div>
  )
}

function ReferenceLabel() {
  const { t } = useTranslation('purchasing')
  return (
    <label htmlFor="po-reference" className="mb-1 block text-sm font-medium text-gray-700">
      {t('poSummary.reference')}
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
  const { t } = useTranslation('purchasing')
  return (
    <div className="space-y-4">
      <CompanyLookup
        id="po-supplier"
        label={t('poSummary.supplier')}
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
              ? t('poSummary.primaryAddressPlaceholder')
              : t('poSummary.noPickupAddress')
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
  const { t } = useTranslation('purchasing')
  const referenceField = useAutosaveField(po.reference ?? '', (value) =>
    patchHeader({ reference: orNull(value) }),
  )
  // Buffered, not PATCHed per keystroke: a date input reports '' whenever any
  // segment is blank, so an operator backspacing the day of a stored date had
  // already sent expected_delivery: null before they finished typing.
  const expectedDeliveryField = useAutosaveField(po.expected_delivery ?? '', (value) =>
    patchHeader({ expected_delivery: orNull(value) }),
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
        <span className="mb-1 block text-sm font-medium text-gray-700">
          {t('poSummary.supplier')}
        </span>
        <p className="py-2 text-sm break-words text-gray-900">
          {po.supplier || t('poSummary.noSupplier')}
        </p>
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
          title={t('poSummary.expectedDeliveryTitle')}
        >
          {t('poSummary.expectedDelivery')}
        </label>
        <input
          id="po-expected-delivery"
          type="date"
          value={expectedDeliveryField.value}
          data-automation-id="PoSummaryCard-expected-delivery"
          className={INPUT_CLASS}
          onChange={(event) => expectedDeliveryField.onChange(event.target.value)}
          onFocus={expectedDeliveryField.onFocus}
          onBlur={expectedDeliveryField.onBlur}
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
