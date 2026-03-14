import { ref, type Ref } from 'vue'
import Sortable from 'sortablejs'
import type { SortableEvent } from 'sortablejs'
import { debugLog } from '../utils/debug'

export interface OptimizedDragEventPayload {
  jobId: string
  fromStatus: string
  toStatus: string
  beforeId?: string
  afterId?: string
}

export type OptimizedDragEventHandler = (event: string, payload: OptimizedDragEventPayload) => void

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
        if (!jobId) return

        const fromCol = evt.from.closest('[data-status]') as HTMLElement
        const toCol = evt.to.closest('[data-status]') as HTMLElement
        const fromStatus = fromCol?.dataset.status
        const toStatus = toCol?.dataset.status
        if (!fromStatus || !toStatus) return

        const newIndex = evt.newIndex ?? 0

        // Get all job IDs from the target column's DOM elements (current state)
        // Use only draggable job-card elements to keep indices aligned with Sortable's newIndex
        const targetColumnJobs: string[] = Array.from(
          evt.to.querySelectorAll<HTMLElement>('.job-card'),
        )
          .map((el) => el.dataset.jobId)
          .filter((id): id is string => !!id)

        // Calculate beforeId and afterId based on the new position in the array
        const beforeId = newIndex > 0 ? targetColumnJobs[newIndex - 1] : undefined
        const afterId =
          newIndex < targetColumnJobs.length - 1 ? targetColumnJobs[newIndex + 1] : undefined

        // Debug positioning for ALL columns to see what's happening
        debugLog(`DRAG POSITIONING: ${fromStatus} -> ${toStatus}`, {
          jobId,
          newIndex,
          beforeId,
          afterId,
          totalChildren: evt.to.children.length,
          targetColumnJobs,
          draggedJobInArray: targetColumnJobs[newIndex],
        })

        // Call the drag event handler (which should handle optimistic updates)
        if (onDragEvent) {
          onDragEvent('job-moved', { jobId, fromStatus, toStatus, beforeId, afterId })
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
