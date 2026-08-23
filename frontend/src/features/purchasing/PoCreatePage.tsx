import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useNavigate, useRouter } from '@tanstack/react-router'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  createPurchaseOrderMutation,
  type CompanySearchResult,
  type SupplierPickupAddressOut,
} from '@/api'
import { Button } from '@/components/ui/button'
import { PoSummaryCard } from './PoSummaryCard'

export function PoCreatePage() {
  const navigate = useNavigate()
  const router = useRouter()
  const [supplier, setSupplier] = useState<CompanySearchResult | null>(null)
  const [reference, setReference] = useState('')
  const [pickupAddress, setPickupAddress] = useState<SupplierPickupAddressOut | null>(null)
  const createPo = useMutation(createPurchaseOrderMutation())

  const save = () => {
    createPo.mutate(
      {
        body: {
          supplier_id: supplier?.id ?? null,
          // ADR 0040: an empty reference is unset, and unset is null.
          reference: reference.trim() === '' ? null : reference,
          // Unset lets the backend pick the supplier's primary address.
          pickup_address_id: pickupAddress?.id ?? null,
        },
      },
      {
        onSuccess: (created) => {
          toast.success('PO created')
          void navigate({ to: '/purchasing/po/$poId', params: { poId: created.id } })
        },
        onError: (error) => {
          toast.error(apiErrorMessage(error, 'Failed to create the purchase order.'))
        },
      },
    )
  }

  return (
    <div className="mx-auto max-w-3xl space-y-8 p-6">
      <h1 className="text-xl font-bold text-gray-900" data-automation-id="PoCreateView-title">
        Create Purchase Order
      </h1>

      <PoSummaryCard
        mode="create"
        supplier={supplier}
        onSelectSupplier={setSupplier}
        reference={reference}
        onReferenceChange={setReference}
        pickupAddress={pickupAddress}
        onSelectPickupAddress={setPickupAddress}
      />

      <div className="flex justify-end gap-2">
        <Button
          variant="secondary"
          disabled={createPo.isPending}
          data-automation-id="PoCreateView-cancel"
          onClick={() => router.history.back()}
        >
          Cancel
        </Button>
        <Button disabled={createPo.isPending} data-automation-id="PoCreateView-save" onClick={save}>
          {createPo.isPending ? 'Creating PO...' : 'Save'}
        </Button>
      </div>
    </div>
  )
}
