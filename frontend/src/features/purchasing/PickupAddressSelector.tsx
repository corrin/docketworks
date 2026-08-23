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
}

/**
 * The PO's pickup address: a read-only display of the chosen one, a button
 * opening the supplier's list, and a clear. Rendered only once the PO has a
 * supplier — the addresses are the supplier's, so without one there is
 * nothing to choose from and the control would be a dead button.
 */
export function PickupAddressSelector({
  supplier,
  selected,
  onChange,
}: PickupAddressSelectorProps) {
  const [open, setOpen] = useState(false)

  return (
    <div>
      <span className="mb-1 block text-sm font-medium text-gray-700">Pickup address</span>
      <div className="flex items-center gap-2">
        <input
          type="text"
          readOnly
          className={`${INPUT_CLASS} bg-gray-50`}
          placeholder="No pickup address selected"
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
      <PickupAddressModal
        open={open}
        supplier={supplier}
        selectedId={selected?.id ?? null}
        onClose={() => setOpen(false)}
        onSelect={(address) => {
          onChange(address)
          setOpen(false)
        }}
      />
    </div>
  )
}
