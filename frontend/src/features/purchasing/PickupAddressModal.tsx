import { useId, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Pencil, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  companiesPickupAddressesCreateMutation,
  companiesPickupAddressesDestroyMutation,
  companiesPickupAddressesListOptions,
  companiesPickupAddressesListQueryKey,
  companiesPickupAddressesUpdateMutation,
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
const orNull = (value: string): string | null => (value.trim() === '' ? null : value)

function requestFrom(form: AddressForm, supplierId: string): SupplierPickupAddressRequest {
  return {
    company: supplierId,
    name: form.name,
    street: form.street,
    suburb: orNull(form.suburb),
    city: form.city,
    state: orNull(form.state),
    postal_code: orNull(form.postal_code),
    notes: orNull(form.notes),
    is_primary: form.is_primary,
    google_place_id: form.google_place_id,
    latitude: form.latitude,
    longitude: form.longitude,
  }
}

const ID = 'PickupAddressSelectionModal'

/**
 * The supplier's pickup addresses: pick one for the PO, or add, edit and
 * delete them. The list and the form share the supplier and the selection,
 * so they are one component; the owner keys it on the supplier, which is
 * what resets an edit in progress when the supplier changes.
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
  const [editing, setEditing] = useState<SupplierPickupAddressOut | null>(null)
  const [form, setForm] = useState<AddressForm>(EMPTY_FORM)
  const [deleteTarget, setDeleteTarget] = useState<SupplierPickupAddressOut | null>(null)
  const ids = {
    name: useId(),
    street: useId(),
    suburb: useId(),
    city: useId(),
    state: useId(),
    postalCode: useId(),
    notes: useId(),
  }

  const invalidate = () =>
    queryClient.invalidateQueries({
      queryKey: companiesPickupAddressesListQueryKey({ query: { supplier_id: supplier.id } }),
    })
  const createMutation = useMutation(companiesPickupAddressesCreateMutation())
  const updateMutation = useMutation(companiesPickupAddressesUpdateMutation())
  const destroyMutation = useMutation(companiesPickupAddressesDestroyMutation())
  const saving = createMutation.isPending || updateMutation.isPending

  const setField = <K extends keyof AddressForm>(key: K, value: AddressForm[K]) =>
    setForm((previous) => ({ ...previous, [key]: value }))

  const resetForm = () => {
    setEditing(null)
    setForm(EMPTY_FORM)
    setDeleteTarget(null)
  }
  const close = () => {
    resetForm()
    onClose()
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
    const body = requestFrom(form, supplier.id)
    if (editing) {
      updateMutation.mutate(
        { path: { id: editing.id }, body },
        {
          onSuccess: () => {
            void invalidate()
            toast.success('Address updated')
            close()
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
          onSelect(created)
          close()
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
          setDeleteTarget(null)
          if (editing?.id === address.id) setEditing(null)
        },
        onError: (error) => toast.error(apiErrorMessage(error, 'Failed to delete the address.')),
      },
    )
  }

  const textField = (
    key: 'suburb' | 'city' | 'state' | 'postal_code',
    label: string,
    inputId: string,
    automationKey: string,
  ) => (
    <label htmlFor={inputId} className="flex flex-col gap-1 text-sm font-medium">
      <span className="text-slate-700">{label}</span>
      <input
        id={inputId}
        type="text"
        className={INPUT_CLASS}
        value={form[key]}
        onChange={(event) => setField(key, event.target.value)}
        data-automation-id={`${ID}-${automationKey}-input`}
      />
    </label>
  )

  return (
    <Dialog open={open} onOpenChange={(next) => !next && close()}>
      <DialogContent
        className="max-h-[90vh] overflow-y-auto sm:max-w-2xl"
        data-automation-id={`${ID}-container`}
      >
        <DialogHeader>
          <DialogTitle>Pickup address for {supplier.name}</DialogTitle>
          <DialogDescription>
            Choose where this order is collected from, or add an address.
          </DialogDescription>
        </DialogHeader>

        <div className="relative">
          {deleteTarget && (
            <div className="absolute inset-0 z-30 flex items-center justify-center rounded-lg bg-white/95">
              <div className="max-w-sm p-6 text-center">
                <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-red-100">
                  <AlertTriangle className="h-6 w-6 text-red-600" />
                </div>
                <h4 className="mb-2 text-lg font-semibold text-gray-900">Delete Address?</h4>
                <p className="mb-4 text-sm text-gray-600">
                  <strong>{deleteTarget.name}</strong> will no longer be offered for this supplier's
                  orders.
                </p>
                <div className="flex justify-center gap-3">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setDeleteTarget(null)}
                    data-automation-id={`${ID}-cancel-delete`}
                  >
                    Cancel
                  </Button>
                  <Button
                    type="button"
                    variant="destructive"
                    disabled={destroyMutation.isPending}
                    onClick={() => remove(deleteTarget)}
                    data-automation-id={`${ID}-confirm-delete`}
                  >
                    Delete
                  </Button>
                </div>
              </div>
            </div>
          )}

          <QueryState
            isPending={listQuery.isPending}
            isError={listQuery.isError}
            onRetry={() => void listQuery.refetch()}
            loadingLabel="pickup addresses"
            errorLabel="pickup addresses"
          >
            {listQuery.data && listQuery.data.length === 0 ? (
              <p className="text-sm text-slate-500">No pickup addresses yet for this supplier.</p>
            ) : (
              <ul className="flex flex-col gap-2" data-automation-id={`${ID}-list`}>
                {(listQuery.data ?? []).map((address) => (
                  <li
                    key={address.id}
                    className="flex items-start justify-between gap-3 rounded-md border border-slate-200 p-3"
                    data-automation-id={`${ID}-address-${address.id}`}
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
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      <Button
                        type="button"
                        size="sm"
                        variant={address.id === selectedId ? 'secondary' : 'default'}
                        onClick={() => onSelect(address)}
                        data-automation-id={`${ID}-select-${address.id}`}
                      >
                        {address.id === selectedId ? 'Selected' : 'Select'}
                      </Button>
                      <Button
                        type="button"
                        size="icon-sm"
                        variant="ghost"
                        title="Edit address"
                        aria-label={`Edit ${address.name}`}
                        onClick={() => {
                          setEditing(address)
                          setForm(formFrom(address))
                        }}
                        data-automation-id={`${ID}-edit-${address.id}`}
                      >
                        <Pencil />
                      </Button>
                      <Button
                        type="button"
                        size="icon-sm"
                        variant="ghost"
                        title="Delete address"
                        aria-label={`Delete ${address.name}`}
                        onClick={() => setDeleteTarget(address)}
                        data-automation-id={`${ID}-delete-${address.id}`}
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
            className="mt-4 flex flex-col gap-3 border-t border-slate-200 pt-4"
            onSubmit={(event) => {
              event.preventDefault()
              if (canSubmit) submit()
            }}
            data-automation-id={`${ID}-form`}
          >
            <h3 className="text-sm font-semibold">
              {editing ? `Edit ${editing.name}` : 'Add an address'}
            </h3>
            <label htmlFor={ids.name} className="flex flex-col gap-1 text-sm font-medium">
              <span className="text-slate-700">Name</span>
              <input
                id={ids.name}
                type="text"
                className={INPUT_CLASS}
                value={form.name}
                placeholder="e.g. Main yard"
                onChange={(event) => setField('name', event.target.value)}
                data-automation-id={`${ID}-name-input`}
              />
            </label>
            <label htmlFor={ids.street} className="flex flex-col gap-1 text-sm font-medium">
              <span className="text-slate-700">Street</span>
              <AddressAutocompleteInput
                id={ids.street}
                value={form.street}
                onChange={(value) =>
                  // A hand-typed street is no longer the geocoded one: the
                  // place id and coordinates described the previous text.
                  setForm((previous) => ({
                    ...previous,
                    street: value,
                    google_place_id: null,
                    latitude: null,
                    longitude: null,
                  }))
                }
                onSelectCandidate={applyCandidate}
              />
            </label>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {textField('suburb', 'Suburb', ids.suburb, 'suburb')}
              {textField('city', 'City', ids.city, 'city')}
              {textField('state', 'State or region', ids.state, 'state')}
              {textField('postal_code', 'Postal code', ids.postalCode, 'postal-code')}
            </div>
            <label htmlFor={ids.notes} className="flex flex-col gap-1 text-sm font-medium">
              <span className="text-slate-700">Notes for the driver</span>
              <textarea
                id={ids.notes}
                className={`${INPUT_CLASS} min-h-16`}
                value={form.notes}
                onChange={(event) => setField('notes', event.target.value)}
                data-automation-id={`${ID}-notes-input`}
              />
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-slate-300"
                checked={form.is_primary}
                onChange={(event) => setField('is_primary', event.target.checked)}
                data-automation-id={`${ID}-primary-input`}
              />
              Primary pickup address for this supplier
            </label>
            <div className="flex justify-end gap-2">
              {editing && (
                <Button type="button" variant="outline" onClick={resetForm}>
                  Cancel edit
                </Button>
              )}
              <Button type="submit" disabled={!canSubmit} data-automation-id={`${ID}-submit`}>
                {saving ? 'Saving…' : editing ? 'Save changes' : 'Add address'}
              </Button>
            </div>
          </form>
        </div>
      </DialogContent>
    </Dialog>
  )
}
