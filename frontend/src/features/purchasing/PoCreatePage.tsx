import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useNavigate, useRouter } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  createPurchaseOrderMutation,
  type CompanySearchResult,
  type SupplierPickupAddressOut,
} from '@/api'
import { Button } from '@/components/ui/button'
import { orNull } from '@/features/shared/nullableText'
import { PoSummaryCard } from './PoSummaryCard'

export function PoCreatePage() {
  const { t } = useTranslation('purchasing')
  const navigate = useNavigate()
  const router = useRouter()
  const [supplier, setSupplier] = useState<CompanySearchResult | null>(null)
  const [reference, setReference] = useState('')
  // undefined until the user touches it: an unsent field lets the backend
  // pick the supplier's primary address; a null is the user's "none".
  const [pickupAddress, setPickupAddress] = useState<SupplierPickupAddressOut | null>()
  const createPo = useMutation(createPurchaseOrderMutation())

  // Xero holds no purchase order without a contact on it, and the order is
  // created there as it is created here, so an order with no supplier is not
  // an order yet. Guarded on the control rather than left to the 422, which
  // names the field but not the reason.
  const save = () => {
    if (supplier === null) return
    createPo.mutate(
      {
        body: {
          supplier_id: supplier.id,
          reference: orNull(reference),
          ...(pickupAddress === undefined ? {} : { pickup_address_id: pickupAddress?.id ?? null }),
        },
      },
      {
        onSuccess: (created) => {
          toast.success(t('poCreate.created'))
          void navigate({ to: '/purchasing/po/$poId', params: { poId: created.id } })
        },
        onError: (error) => {
          toast.error(apiErrorMessage(error, t('poCreate.createFailed')))
        },
      },
    )
  }

  return (
    <div className="mx-auto max-w-3xl space-y-8 p-6">
      <h1 className="text-xl font-bold text-gray-900" data-automation-id="PoCreateView-title">
        {t('poCreate.title')}
      </h1>

      <PoSummaryCard
        mode="create"
        supplier={supplier}
        onSelectSupplier={setSupplier}
        reference={reference}
        onReferenceChange={setReference}
        pickupAddress={pickupAddress}
        onSelectPickupAddress={setPickupAddress}
        onResetPickupAddress={() => setPickupAddress(undefined)}
      />

      <div className="flex justify-end gap-2">
        <Button
          variant="secondary"
          disabled={createPo.isPending}
          data-automation-id="PoCreateView-cancel"
          onClick={() => router.history.back()}
        >
          {t('poCreate.cancel')}
        </Button>
        <Button
          disabled={createPo.isPending || supplier === null}
          title={supplier === null ? t('poCreate.chooseSupplierFirst') : undefined}
          data-automation-id="PoCreateView-save"
          onClick={save}
        >
          {createPo.isPending ? t('poCreate.creating') : t('poCreate.save')}
        </Button>
      </div>
    </div>
  )
}
