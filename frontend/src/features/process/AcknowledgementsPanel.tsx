import { useMemo } from 'react'
import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  processFormsAcknowledgeCreateMutation,
  processFormsAcknowledgementsListOptions,
  processFormsAcknowledgementsListQueryKey,
  type AcknowledgementOut,
} from '@/api'
import { Button } from '@/components/ui/button'
import { meQueryOptions } from '@/features/auth'
import { QueryState } from '@/features/shared/QueryState'
import { formatDateTime } from '@/lib/format'

/** The list is newest-first (Meta ordering on the backend); keep the first
    row seen per staff id so a repeat acknowledgement's earlier rows for the
    same staff member drop out, leaving one row per staff member. */
function latestPerStaff(rows: AcknowledgementOut[]): AcknowledgementOut[] {
  const seen = new Set<string>()
  const latest: AcknowledgementOut[] = []
  for (const row of rows) {
    if (seen.has(row.staff)) continue
    seen.add(row.staff)
    latest.push(row)
  }
  return latest
}

/**
 * "I have read and understood this document": records a read receipt for
 * the signed-in staff member and lists every staff member's latest one.
 * Mounted in `FormEntriesPage`'s header, under the title/badges.
 */
export function AcknowledgementsPanel({ formId }: { formId: string }) {
  const { data: user } = useSuspenseQuery(meQueryOptions())
  const queryClient = useQueryClient()
  const listQuery = useQuery(processFormsAcknowledgementsListOptions({ path: { form_id: formId } }))
  const acknowledgeMutation = useMutation(processFormsAcknowledgeCreateMutation())

  const latest = useMemo(() => latestPerStaff(listQuery.data ?? []), [listQuery.data])
  const alreadyAcknowledged = latest.some((row) => row.staff === user.id)

  async function handleAcknowledge(): Promise<void> {
    try {
      // AcknowledgeIn is a zero-field extra=forbid schema: the empty object
      // is the whole contract, not a placeholder for fields to come.
      await acknowledgeMutation.mutateAsync({ path: { form_id: formId }, body: {} })
      await queryClient.invalidateQueries({
        queryKey: processFormsAcknowledgementsListQueryKey({ path: { form_id: formId } }),
      })
      toast.success('Acknowledged')
    } catch (error) {
      toast.error(apiErrorMessage(error, 'Could not record the acknowledgement.'))
    }
  }

  return (
    <div className="mt-2 flex flex-col gap-2" data-automation-id="Acknowledgements-panel">
      <div className="flex flex-wrap items-center gap-3">
        <h2
          className="text-sm font-semibold text-slate-700"
          data-automation-id="Acknowledgements-count"
        >
          Acknowledgements ({latest.length})
        </h2>
        <Button
          size="sm"
          variant="outline"
          disabled={acknowledgeMutation.isPending}
          onClick={() => void handleAcknowledge()}
          data-automation-id="Acknowledgements-button"
        >
          {alreadyAcknowledged ? 'Acknowledge again' : 'I have read and understood this document'}
        </Button>
      </div>
      <QueryState
        isPending={listQuery.isPending}
        isError={listQuery.isError}
        onRetry={() => void listQuery.refetch()}
        loadingLabel="Loading acknowledgements..."
        errorLabel="Failed to load acknowledgements."
      >
        {latest.length === 0 ? (
          <p className="text-xs text-slate-500" data-automation-id="Acknowledgements-empty">
            No one has acknowledged this document yet.
          </p>
        ) : (
          <ul className="flex flex-col gap-1 text-xs text-slate-600">
            {latest.map((row) => (
              <li key={row.id} data-automation-id={`Acknowledgements-row-${row.id}`}>
                {row.staff_name} — {formatDateTime(row.acknowledged_at)}
              </li>
            ))}
          </ul>
        )}
      </QueryState>
    </div>
  )
}
