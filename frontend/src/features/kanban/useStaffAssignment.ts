/**
 * The board's staff concern: who is in the panel, and putting one of them on
 * a card. Both live here because the assignment's optimistic avatar is built
 * from the panel's own row — a second staff query would let the panel and the
 * card disagree about a person's name or icon.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect } from 'react'
import { toast } from 'sonner'

import { accountsStaffAllListOptions, apiErrorMessage, jobJobAssignmentCreateMutation } from '@/api'
import type { KanbanStaffOut } from '@/api'
import { localIsoDate } from '@/lib/format'

import {
  columnQueryKey,
  findColumnJob,
  restoreSnapshot,
  snapshotColumns,
  updateJobInPlace,
} from './boardCache'

/** v1 useStaffApi.listStaffForKanban: today's actual users, payroll rows excluded. */
export function kanbanStaffQueryOptions() {
  return accountsStaffAllListOptions({ query: { actual_users: true, date: localIsoDate() } })
}

export interface StaffAssignment {
  staff: KanbanStaffOut[]
  isStaffLoading: boolean
  assignStaff: (jobId: string, staffId: string) => void
}

export function useStaffAssignment(): StaffAssignment {
  const queryClient = useQueryClient()
  const staffQuery = useQuery(kanbanStaffQueryOptions())
  const assign = useMutation(jobJobAssignmentCreateMutation())

  // Toasted rather than thrown: the panel is one strip of the board and the
  // columns behind it stay usable. In an effect, not in render — a render-time
  // toast fires twice under StrictMode.
  const staffError = staffQuery.error
  useEffect(() => {
    if (staffError) {
      toast.error(apiErrorMessage(staffError, 'Failed to load the staff panel'))
    }
  }, [staffError])

  const assignStaff = useCallback(
    (jobId: string, staffId: string) => {
      const job = findColumnJob(queryClient, jobId)
      if (!job) {
        // The card is not in a loaded column (a search hit past the fetch
        // window): persist without an optimistic avatar and let the settle
        // invalidation show the result.
        assign.mutate({ path: { job_id: jobId }, body: { staff_id: staffId } })
        return
      }
      if (job.people.some((person) => person.id === staffId)) return

      const snapshot = snapshotColumns(queryClient, [job.status_key])
      const person = staffQuery.data?.find((candidate) => candidate.id === staffId)
      if (person) {
        updateJobInPlace(queryClient, jobId, (current) => ({
          ...current,
          people: [
            ...current.people,
            { id: person.id, display_name: person.display_name, icon_url: person.icon_url },
          ],
        }))
      }

      assign.mutate(
        { path: { job_id: jobId }, body: { staff_id: staffId } },
        {
          onError: (error) => {
            toast.error(apiErrorMessage(error, 'Failed to assign the staff member'))
            restoreSnapshot(queryClient, snapshot)
          },
          // Unlike a reorder, a refetch here cannot disturb anything the user
          // just did: assignment does not change column order, so server
          // truth for `people` is free to overwrite the optimistic avatar.
          onSettled: () => {
            void queryClient.invalidateQueries({ queryKey: columnQueryKey(job.status_key) })
          },
        },
      )
    },
    [assign, queryClient, staffQuery.data],
  )

  // SEAM: unassignment (v1's hover-X on a card avatar) has no ported spec and
  // no UI this PR; it lands with the mobile/staff slice as a sibling mutation
  // (jobJobAssignmentDestroyMutation) rolling back through the same snapshot.

  return {
    staff: staffQuery.data ?? [],
    isStaffLoading: staffQuery.isPending,
    assignStaff,
  }
}
