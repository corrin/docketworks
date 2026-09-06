import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  createPurchaseOrderEventMutation,
  listPurchaseOrderEventsOptions,
  listPurchaseOrderEventsQueryKey,
} from '@/api'
import { Button } from '@/components/ui/button'
import { INPUT_CLASS } from '@/components/ui/field'
import { EntryGridSection } from '@/features/shared/EntryGridSection'
import { QueryState } from '@/features/shared/QueryState'
import { formatDateTime } from '@/lib/format'

interface PoHistorySectionProps {
  poId: string
}

export function PoHistorySection({ poId }: PoHistorySectionProps) {
  const queryClient = useQueryClient()
  const history = useQuery(listPurchaseOrderEventsOptions({ path: { po_id: poId } }))
  const [isAdding, setIsAdding] = useState(false)
  const [description, setDescription] = useState('')
  const addNote = useMutation({
    ...createPurchaseOrderEventMutation(),
    onSuccess: () => {
      setDescription('')
      setIsAdding(false)
      void queryClient.invalidateQueries({
        queryKey: listPurchaseOrderEventsQueryKey({ path: { po_id: poId } }),
      })
      toast.success('Note added')
    },
    onError: (error) => toast.error(apiErrorMessage(error, 'Failed to add the note.')),
  })

  return (
    <EntryGridSection
      title="Notes & History"
      actions={
        <Button
          type="button"
          variant="outline"
          aria-expanded={isAdding}
          aria-controls="po-note-form"
          disabled={addNote.isPending}
          onClick={() => setIsAdding(!isAdding)}
        >
          Add note
        </Button>
      }
    >
      {isAdding && (
        <form
          id="po-note-form"
          className="mb-4 space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-4"
          onSubmit={(event) => {
            event.preventDefault()
            if (addNote.isPending || description.trim() === '') return
            addNote.mutate({ path: { po_id: poId }, body: { description } })
          }}
        >
          <label htmlFor="po-note-description" className="block text-sm font-medium text-gray-700">
            Note
          </label>
          <textarea
            id="po-note-description"
            rows={3}
            className={INPUT_CLASS}
            value={description}
            disabled={addNote.isPending}
            onChange={(event) => setDescription(event.target.value)}
          />
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={addNote.isPending}
              onClick={() => setIsAdding(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={addNote.isPending || description.trim() === ''}>
              {addNote.isPending ? 'Saving…' : 'Save note'}
            </Button>
          </div>
        </form>
      )}
      {history.isError && history.data !== undefined && (
        <p role="alert" className="mb-3 text-sm text-red-600">
          Could not refresh notes.{' '}
          <button className="underline" onClick={() => void history.refetch()}>
            Retry
          </button>
        </p>
      )}
      <QueryState
        isPending={history.isPending}
        isError={history.isError && history.data === undefined}
        loadingLabel="Loading notes…"
        errorLabel="Could not load notes."
        onRetry={() => void history.refetch()}
      >
        {history.data &&
          (history.data.events.length === 0 ? (
            <p className="py-4 text-sm text-slate-500">No notes yet.</p>
          ) : (
            <ol className="divide-y divide-slate-200">
              {history.data.events.map((entry) => (
                <li key={entry.id} className="py-4">
                  <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500">
                    <span className="font-medium text-gray-700">{entry.staff}</span>
                    <time dateTime={entry.timestamp}>{formatDateTime(entry.timestamp)}</time>
                  </div>
                  <p className="mt-2 text-sm whitespace-pre-wrap break-words text-gray-900">
                    {entry.description}
                  </p>
                </li>
              ))}
            </ol>
          ))}
      </QueryState>
    </EntryGridSection>
  )
}
