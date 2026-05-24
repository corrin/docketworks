import { ref, type Ref } from 'vue'
import Sortable from 'sortablejs'
import type { SortableEvent } from 'sortablejs'
import { debugLog } from '../utils/debug'

export interface OptimizedDragEventPayload {
  jobId: string
  fromStatus: string
  toStatus: string
  anchorJobId?: string
  placement?: 'above' | 'below'
}

export type OptimizedDragEventHandler = (event: string, payload: OptimizedDragEventPayload) => void

function getVisibleJobAnchor(
  container: HTMLElement,
  movedElement: HTMLElement,
  movedJobId: string,
): { anchorJobId?: string; placement?: 'above' | 'below'; targetColumnJobs: string[] } {
  const jobElements = Array.from(container.querySelectorAll<HTMLElement>('.job-card')).filter(
    (el) => el.dataset.jobId,
  )
  const targetColumnJobs = jobElements
    .map((el) => el.dataset.jobId)
    .filter((id): id is string => !!id)
  const movedIndex = jobElements.findIndex(
    (el) => el === movedElement || el.dataset.jobId === movedJobId,
  )

  if (movedIndex === -1) {
    return { targetColumnJobs }
  }

  const previousJobId = [...jobElements]
    .slice(0, movedIndex)
    .reverse()
    .find((el) => el.dataset.jobId && el.dataset.jobId !== movedJobId)?.dataset.jobId
  if (previousJobId) {
    return { anchorJobId: previousJobId, placement: 'below', targetColumnJobs }
  }

  const nextJobId = jobElements
    .slice(movedIndex + 1)
    .find((el) => el.dataset.jobId && el.dataset.jobId !== movedJobId)?.dataset.jobId
  if (nextJobId) {
    return { anchorJobId: nextJobId, placement: 'above', targetColumnJobs }
  }

  return { targetColumnJobs }
}

export function useOptimizedDragAndDrop(onDragEvent?: OptimizedDragEventHandler) {
  const isDragging = ref(false)
  const sortableInstances = ref<Map<string, Sortable>>(new Map())
  let idleCleanupTimer: ReturnType<typeof setInterval> | null = null

  // Periodically check for stuck drag state and log diagnostics
  const startIdleCleanup = () => {
    if (idleCleanupTimer) return
    idleCleanupTimer = setInterval(() => {
      const ghostEls = document.querySelectorAll('.sortable-ghost')
      const chosenEls = document.querySelectorAll('.sortable-chosen')
      const dragEls = document.querySelectorAll('.sortable-drag')
      debugLog('IDLE CHECK', {
        isDraggingRef: isDragging.value,
        sortableGhosts: ghostEls.length,
        sortableChosen: chosenEls.length,
        sortableDrag: dragEls.length,
        bodyHasDragging: document.body.classList.contains('is-dragging'),
      })
    }, 5_000)
  }

  const initializeSortable = (element: HTMLElement, status: string) => {
    const existing = sortableInstances.value.get(status)
    if (existing) {
      existing.destroy()
      sortableInstances.value.delete(status)
    }
    if (!element || !element.isConnected) return

    debugLog(`Creating Sortable for ${status}:`, {
      children: element.children.length,
    })

    const sortableConfig = {
      group: 'kanban-jobs',
      animation: 150,
      draggable: '.job-card',
      sort: true,
      emptyInsertThreshold: 100,
      forceFallback: false,
      fallbackOnBody: true,
      swapThreshold: 0.65,
      onStart: () => {
        debugLog('DRAG START -- setting isDragging=true')
        isDragging.value = true
        document.body.classList.add('is-dragging')
      },
      onMove: () => {
        return true
      },
      onEnd: async (evt: SortableEvent) => {
        debugLog('DRAG END -- setting isDragging=false')
        isDragging.value = false
        document.body.classList.remove('is-dragging')

        // Clean up SortableJS CSS classes that persist on the dragged element
        const jobElement = evt.item as HTMLElement
        jobElement.classList.remove('sortable-chosen', 'sortable-drag', 'sortable-ghost')

        const jobId = jobElement.dataset.jobId
        const fromStatus = (evt.from.closest('[data-status]') as HTMLElement | null)?.dataset.status
        const toStatus = (evt.to.closest('[data-status]') as HTMLElement | null)?.dataset.status

        // Capture the drop position from the DOM *before* detaching the node —
        // Sortable's newIndex counts the moved element among its new siblings.
        let anchorJobId: string | undefined
        let placement: 'above' | 'below' | undefined
        let targetColumnJobs: string[] = []
        if (jobId && fromStatus && toStatus) {
          const newIndex = evt.newIndex ?? 0
          const anchor = getVisibleJobAnchor(evt.to, jobElement, jobId)
          anchorJobId = anchor.anchorJobId
          placement = anchor.placement
          targetColumnJobs = anchor.targetColumnJobs

          debugLog(`DRAG POSITIONING: ${fromStatus} -> ${toStatus}`, {
            jobId,
            newIndex,
            anchorJobId,
            placement,
            totalChildren: evt.to.children.length,
            targetColumnJobs,
            draggedJobInArray: targetColumnJobs[newIndex],
          })
        } else {
          debugLog('DRAG END -- missing jobId/from/to status; skipping move event', {
            jobId,
            fromStatus,
            toStatus,
          })
        }

        // Call the drag event handler (which should handle optimistic updates)
        if (jobId && fromStatus && toStatus && onDragEvent) {
          onDragEvent('job-moved', { jobId, fromStatus, toStatus, anchorJobId, placement })
        }

        if (jobId) {
          debugLog('DRAG END -- post-handler DOM state', {
            jobId,
            draggedElementConnected: jobElement.isConnected,
            matchingCards: document.querySelectorAll(`[data-job-id="${jobId}"]`).length,
            matchingVisibleCards: document.querySelectorAll(
              `[data-job-id="${jobId}"]:not([hidden])`,
            ).length,
          })
        }

        // Revalidation is handled by the onDragEvent handler (useOptimizedKanban)
        // Removing duplicate revalidation to prevent conflicts and duplications
      },
    }

    const sortable = Sortable.create(element, sortableConfig)

    sortableInstances.value.set(status, sortable)
    startIdleCleanup()
  }

  const destroyAllSortables = () => {
    if (idleCleanupTimer) {
      clearInterval(idleCleanupTimer)
      idleCleanupTimer = null
    }
    sortableInstances.value.forEach((sortable) => sortable.destroy())
    sortableInstances.value.clear()
    isDragging.value = false
    document.body.classList.remove('is-dragging')
  }

  return {
    isDragging: isDragging as Ref<boolean>,
    initializeSortable,
    destroyAllSortables,
  }
}
