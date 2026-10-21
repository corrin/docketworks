import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  createPurchaseOrderEventMutation,
  listPurchaseOrderEventsOptions,
  listPurchaseOrderEventsQueryKey,
} from '@/api'
import { Button } from '@/components/ui/button'
import { INPUT_CLASS } from '@/components/ui/field'
import { AuditEventList } from '@/features/shared/AuditEventList'
import { EntryGridSection } from '@/features/shared/EntryGridSection'
import { QueryState } from '@/features/shared/QueryState'

interface PoHistorySectionProps {
  poId: string
}

export function PoHistorySection({ poId }: PoHistorySectionProps) {
  const { t } = useTranslation('purchasing')
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
      toast.success(t('poHistory.noteAdded'))
    },
    onError: (error) => toast.error(apiErrorMessage(error, t('poHistory.addFailed'))),
  })

  return (
    <EntryGridSection
      title={t('poHistory.title')}
      actions={
        <Button
          type="button"
          variant="outline"
          aria-expanded={isAdding}
          aria-controls="po-note-form"
          disabled={addNote.isPending}
          onClick={() => setIsAdding(!isAdding)}
        >
          {t('poHistory.addNote')}
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
            {t('poHistory.note')}
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
              {t('poHistory.cancel')}
            </Button>
            <Button type="submit" disabled={addNote.isPending || description.trim() === ''}>
              {addNote.isPending ? t('poHistory.saving') : t('poHistory.saveNote')}
            </Button>
          </div>
        </form>
      )}
      {history.isError && history.data !== undefined && (
        <p role="alert" className="mb-3 text-sm text-red-600">
          {t('poHistory.refreshFailed')}{' '}
          <button className="underline" onClick={() => void history.refetch()}>
            {t('poHistory.retry')}
          </button>
        </p>
      )}
      <QueryState
        isPending={history.isPending}
        isError={history.isError && history.data === undefined}
        loadingLabel={t('poHistory.loading')}
        errorLabel={t('poHistory.loadFailed')}
        onRetry={() => void history.refetch()}
      >
        {history.data && (
          <AuditEventList
            events={history.data.events}
            automationIdPrefix="PoHistorySection"
            emptyLabel={t('poHistory.empty')}
          />
        )}
      </QueryState>
    </EntryGridSection>
  )
}
