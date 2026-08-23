import { useState } from 'react'
import { MapPin, X } from 'lucide-react'

import type { SupplierPickupAddressOut } from '@/api'
import { Button } from '@/components/ui/button'
import { INPUT_CLASS } from '@/components/ui/field'
import { PickupAddressModal, type PickupSupplier } from './PickupAddressModal'

interface PickupAddressSelectorProps {
  supplier: PickupSupplier
  selected: SupplierPickupAddressOut | null
  onChange: (address: SupplierPickupAddressOut | null) => void
  /** Shown while nothing is selected; the create page says what the backend will do instead. */
  placeholder?: string
}

/**
 * The PO's pickup address: a read-only display of the chosen one, a button
 * opening the supplier's list, and a clear. The owner renders it only once
 * the PO has a supplier, because the addresses are the supplier's.
 */
export function PickupAddressSelector({
  supplier,
  selected,
  onChange,
  placeholder = 'No pickup address selected',
}: PickupAddressSelectorProps) {
  const [open, setOpen] = useState(false)

  return (
    <div>
      <span className="mb-1 block text-sm font-medium text-gray-700">Pickup address</span>
      <div className="flex items-center gap-2">
        {/* An input, not a span: the E2E contract reads this via inputValue(). */}
        <input
          type="text"
          readOnly
          className={`${INPUT_CLASS} bg-gray-50`}
          placeholder={placeholder}
          aria-label="Pickup address"
          value={selected?.formatted_address ?? ''}
          data-automation-id="PickupAddressSelector-display"
        />
        <Button
          type="button"
          size="icon"
          variant="outline"
          title="Choose pickup address"
          aria-label="Choose pickup address"
          onClick={() => setOpen(true)}
          data-automation-id="PickupAddressSelector-modal-button"
        >
          <MapPin />
        </Button>
        {selected && (
          <Button
            type="button"
            size="icon"
            variant="ghost"
            title="Clear pickup address"
            aria-label="Clear pickup address"
            onClick={() => onChange(null)}
            data-automation-id="PickupAddressSelector-clear-button"
          >
            <X />
          </Button>
        )}
      </div>
      {/* Keyed on the supplier so an edit in progress never outlives the
          supplier it belonged to. */}
      <PickupAddressModal
        key={supplier.id}
        open={open}
        supplier={supplier}
        selectedId={selected?.id ?? null}
        onClose={() => setOpen(false)}
        onSelect={(address) => {
          onChange(address)
          setOpen(false)
        }}
        // The chosen address is what the PO prints; an edit or deletion of
        // that very address must reach the PO, not only the list.
        onUpdated={(address) => {
          if (address.id === selected?.id) onChange(address)
        }}
        onDeleted={(addressId) => {
          if (addressId === selected?.id) onChange(null)
        }}
      />
    </div>
  )
}
