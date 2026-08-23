import { useId, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  companiesPickupAddressesCreateMutation,
  companiesPickupAddressesDestroyMutation,
  companiesPickupAddressesListOptions,
  companiesPickupAddressesListQueryKey,
  companiesPickupAddressesPartialUpdateMutation,
  type AddressCandidate,
  type SupplierPickupAddressOut,
  type SupplierPickupAddressRequest,
} from '@/api'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { INPUT_CLASS } from '@/components/ui/field'
import { QueryState } from '@/features/shared/QueryState'
import { AddressAutocompleteInput } from '@/features/shared/address/AddressAutocompleteInput'

export interface PickupSupplier {
  id: string
  name: string
}

interface PickupAddressModalProps {
  open: boolean
  supplier: PickupSupplier
  selectedId: string | null
  onClose: () => void
  onSelect: (address: SupplierPickupAddressOut) => void
}

interface AddressForm {
  name: string
  street: string
  suburb: string
  city: string
  state: string
  postal_code: string
  notes: string
  is_primary: boolean
  google_place_id: string | null
  latitude: number | null
  longitude: number | null
}

const EMPTY_FORM: AddressForm = {
  name: '',
  street: '',
  suburb: '',
  city: '',
  state: '',
  postal_code: '',
  notes: '',
  is_primary: false,
  google_place_id: null,
  latitude: null,
  longitude: null,
}

function formFrom(address: SupplierPickupAddressOut): AddressForm {
  return {
    name: address.name,
    street: address.street,
    suburb: address.suburb ?? '',
    city: address.city,
    state: address.state ?? '',
    postal_code: address.postal_code ?? '',
    notes: address.notes ?? '',
    is_primary: address.is_primary,
    google_place_id: address.google_place_id,
    latitude: address.latitude,
    longitude: address.longitude,
  }
}

/** ADR 0040: an emptied optional box is unset, and unset is null. */
const orNull = (value: string): string | null => (value.trim() === '' ? null : value.trim())

function requestFrom(form: AddressForm, supplierId: string): SupplierPickupAddressRequest {
  return {
    company: supplierId,
    name: form.name.trim(),
    street: form.street.trim(),
    suburb: orNull(form.suburb),
    city: form.city.trim(),
    state: orNull(form.state),
    postal_code: orNull(form.postal_code),
    notes: orNull(form.notes),
    is_primary: form.is_primary,
    google_place_id: form.google_place_id,
    latitude: form.latitude,
    longitude: form.longitude,
  }
}

/**
 * The supplier's pickup addresses: pick one for the PO, or add, edit and
 * delete them. One modal for all four because the list and the form share
 * the supplier and the selection; v1 split the same screen across a modal,
 * a composable and two child components.
 */
export function PickupAddressModal({
  open,
  supplier,
  selectedId,
  onClose,
  onSelect,
}: PickupAddressModalProps) {
  const queryClient = useQueryClient()
  const listQuery = useQuery({
    ...companiesPickupAddressesListOptions({ query: { supplier_id: supplier.id } }),
    enabled: open,
  })
  const addresses = listQuery.data ?? []
  const [editing, setEditing] = useState<SupplierPickupAddressOut | null>(null)
  const [form, setForm] = useState<AddressForm>(EMPTY_FORM)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)
  const nameId = useId()
  const streetId = useId()

  const invalidate = () =>
    queryClient.invalidateQueries({
      queryKey: companiesPickupAddressesListQueryKey({ query: { supplier_id: supplier.id } }),
    })
  const createMutation = useMutation(companiesPickupAddressesCreateMutation())
  const updateMutation = useMutation(companiesPickupAddressesPartialUpdateMutation())
  const destroyMutation = useMutation(companiesPickupAddressesDestroyMutation())
  const saving = createMutation.isPending || updateMutation.isPending

  const setField = <K extends keyof AddressForm>(key: K, value: AddressForm[K]) =>
    setForm((previous) => ({ ...previous, [key]: value }))

  const startEdit = (address: SupplierPickupAddressOut) => {
    setEditing(address)
    setForm(formFrom(address))
  }
  const cancelEdit = () => {
    setEditing(null)
    setForm(EMPTY_FORM)
  }

  const applyCandidate = (candidate: AddressCandidate) => {
    setForm((previous) => ({
      ...previous,
      street: candidate.street,
      suburb: candidate.suburb,
      city: candidate.city,
      state: candidate.state,
      postal_code: candidate.postal_code,
      google_place_id: candidate.google_place_id,
      latitude: candidate.latitude,
      longitude: candidate.longitude,
    }))
  }

  const canSubmit =
    form.name.trim() !== '' && form.street.trim() !== '' && form.city.trim() !== '' && !saving

  const submit = () => {
    // The first address a supplier gets is its primary: PO creation without
    // an explicit choice resolves to the primary, and a supplier whose only
    // address is not primary would resolve to nothing.
    const body = requestFrom(
      { ...form, is_primary: form.is_primary || (editing === null && addresses.length === 0) },
      supplier.id,
    )
    if (editing) {
      updateMutation.mutate(
        { path: { id: editing.id }, body },
        {
          onSuccess: () => {
            void invalidate()
            toast.success('Address updated')
            cancelEdit()
            onClose()
          },
          onError: (error) => toast.error(apiErrorMessage(error, 'Failed to update the address.')),
        },
      )
      return
    }
    createMutation.mutate(
      { body },
      {
        onSuccess: (created) => {
          void invalidate()
          toast.success('Address created')
          setForm(EMPTY_FORM)
          onSelect(created)
          onClose()
        },
        onError: (error) => toast.error(apiErrorMessage(error, 'Failed to create the address.')),
      },
    )
  }

  const remove = (address: SupplierPickupAddressOut) => {
    destroyMutation.mutate(
      { path: { id: address.id } },
      {
        onSuccess: () => {
          void invalidate()
          toast.success('Address deleted')
          setConfirmDeleteId(null)
          if (editing?.id === address.id) cancelEdit()
        },
        onError: (error) => toast.error(apiErrorMessage(error, 'Failed to delete the address.')),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent
        className="max-h-[90vh] overflow-y-auto sm:max-w-2xl"
        data-automation-id="PickupAddressSelectionModal-container"
      >
        <DialogHeader>
          <DialogTitle>Pickup address for {supplier.name}</DialogTitle>
          <DialogDescription>
            Choose where this order is collected from, or add an address.
          </DialogDescription>
        </DialogHeader>

        <QueryState
          isPending={listQuery.isPending}
          isError={listQuery.isError}
          onRetry={() => void listQuery.refetch()}
          loadingLabel="pickup addresses"
          errorLabel="pickup addresses"
        >
          {addresses.length === 0 ? (
            <p className="text-sm text-slate-500">No pickup addresses yet for this supplier.</p>
          ) : (
            <ul
              className="flex flex-col gap-2"
              data-automation-id="PickupAddressSelectionModal-list"
            >
              {addresses.map((address) => (
                <li
                  key={address.id}
                  className="flex items-start justify-between gap-3 rounded-md border border-slate-200 p-3"
                  data-automation-id={`PickupAddressSelectionModal-address-${address.id}`}
                >
                  <div className="min-w-0 text-sm">
                    <div className="font-medium">
                      {address.name}
                      {address.is_primary && (
                        <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-xs font-normal text-slate-600">
                          Primary
                        </span>
                      )}
                    </div>
                    <div className="text-slate-600">{address.formatted_address}</div>
                    {confirmDeleteId === address.id && (
                      <div className="mt-2 flex items-center gap-2 rounded-md border border-red-200 bg-red-50 p-2">
                        <span className="text-red-800">Delete Address?</span>
                        <Button
                          size="xs"
                          variant="destructive"
                          disabled={destroyMutation.isPending}
                          onClick={() => remove(address)}
                        >
                          Delete
                        </Button>
                        <Button size="xs" variant="ghost" onClick={() => setConfirmDeleteId(null)}>
                          Cancel
                        </Button>
                      </div>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <Button
                      size="sm"
                      variant={address.id === selectedId ? 'secondary' : 'default'}
                      onClick={() => onSelect(address)}
                      data-automation-id="PickupAddressSelectionModal-select-button"
                    >
                      {address.id === selectedId ? 'Selected' : 'Select'}
                    </Button>
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      title="Edit address"
                      aria-label={`Edit ${address.name}`}
                      onClick={() => startEdit(address)}
                    >
                      <Pencil />
                    </Button>
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      title="Delete address"
                      aria-label={`Delete ${address.name}`}
                      onClick={() => setConfirmDeleteId(address.id)}
                    >
                      <Trash2 />
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </QueryState>

        <form
          className="mt-2 flex flex-col gap-3 border-t border-slate-200 pt-4"
          onSubmit={(event) => {
            event.preventDefault()
            if (canSubmit) submit()
          }}
          data-automation-id="PickupAddressSelectionModal-form"
        >
          <h3 className="text-sm font-semibold">
            {editing ? `Edit ${editing.name}` : 'Add an address'}
          </h3>
          <label htmlFor={nameId} className="flex flex-col gap-1 text-sm font-medium">
            <span className="text-slate-700">Name</span>
            <input
              id={nameId}
              type="text"
              className={INPUT_CLASS}
              value={form.name}
              placeholder="e.g. Main yard"
              onChange={(event) => setField('name', event.target.value)}
              data-automation-id="PickupAddressSelectionModal-name-input"
            />
          </label>
          <label htmlFor={streetId} className="flex flex-col gap-1 text-sm font-medium">
            <span className="text-slate-700">Street</span>
            <AddressAutocompleteInput
              id={streetId}
              value={form.street}
              onChange={(value) => setField('street', value)}
              onSelectCandidate={applyCandidate}
            />
          </label>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <input
              type="text"
              className={INPUT_CLASS}
              placeholder="Suburb"
              aria-label="Suburb"
              value={form.suburb}
              onChange={(event) => setField('suburb', event.target.value)}
            />
            <input
              type="text"
              className={INPUT_CLASS}
              placeholder="City"
              aria-label="City"
              value={form.city}
              onChange={(event) => setField('city', event.target.value)}
            />
            <input
              type="text"
              className={INPUT_CLASS}
              placeholder="State or region"
              aria-label="State or region"
              value={form.state}
              onChange={(event) => setField('state', event.target.value)}
            />
            <input
              type="text"
              className={INPUT_CLASS}
              placeholder="Postal code"
              aria-label="Postal code"
              value={form.postal_code}
              onChange={(event) => setField('postal_code', event.target.value)}
            />
          </div>
          <textarea
            className={`${INPUT_CLASS} min-h-16`}
            placeholder="Notes for the driver"
            aria-label="Notes"
            value={form.notes}
            onChange={(event) => setField('notes', event.target.value)}
          />
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-slate-300"
              checked={form.is_primary}
              onChange={(event) => setField('is_primary', event.target.checked)}
            />
            Primary pickup address for this supplier
          </label>
          <div className="flex justify-end gap-2">
            {editing && (
              <Button type="button" variant="outline" onClick={cancelEdit}>
                Cancel edit
              </Button>
            )}
            <Button
              type="submit"
              disabled={!canSubmit}
              data-automation-id="PickupAddressSelectionModal-submit"
            >
              {saving ? 'Saving…' : editing ? 'Save changes' : 'Add address'}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
