/**
 * Card drag-and-drop, on pragmatic-drag-and-drop.
 *
 * Every registration is made in an effect whose dependencies exclude the
 * changing values it reads (they come from refs instead). Re-registering a
 * draggable or a drop target while a drag is in flight tears it out from
 * under the pointer and the drag dies silently — the failure mode looks like
 * "drops sometimes do nothing", so the refs are load-bearing, not style.
 */
import { combine } from '@atlaskit/pragmatic-drag-and-drop/combine'
import {
  draggable,
  dropTargetForElements,
  monitorForElements,
} from '@atlaskit/pragmatic-drag-and-drop/element/adapter'
import { autoScrollForElements } from '@atlaskit/pragmatic-drag-and-drop-auto-scroll/element'
import {
  attachClosestEdge,
  extractClosestEdge,
} from '@atlaskit/pragmatic-drag-and-drop-hitbox/closest-edge'
import type { ElementDropTargetGetFeedbackArgs } from '@atlaskit/pragmatic-drag-and-drop/element/adapter'
import { useCallback, useEffect, useRef, useState } from 'react'

import type { MoveJobRequest } from './useKanbanBoard'

const JOB_CARD_TYPE = 'job-card'
const COLUMN_TYPE = 'kanban-column'

// Pragmatic types drag payloads as open records, so these extend one rather
// than being cast into place at every call site.
type DragPayload = Record<string | symbol, unknown>

interface JobCardDragData extends DragPayload {
  type: typeof JOB_CARD_TYPE
  jobId: string
  statusKey: string
}

interface ColumnDropData extends DragPayload {
  type: typeof COLUMN_TYPE
  statusKey: string
  /** The last card currently displayed, the anchor for a column-only drop. */
  lastJobId: string | null
}

function isJobCardData(data: DragPayload): data is JobCardDragData {
  return data.type === JOB_CARD_TYPE
}

function isColumnData(data: DragPayload): data is ColumnDropData {
  return data.type === COLUMN_TYPE
}

type DropTargetRecord = { data: DragPayload }

/**
 * Turn a drop into a move request, or null when nothing should happen.
 *
 * dropTargets is innermost-first: [card, column] when the pointer is over a
 * card, [column] over blank column space, and empty when the drag was
 * cancelled or released outside the board.
 */
function resolveDrop(
  source: JobCardDragData,
  dropTargets: readonly DropTargetRecord[],
): MoveJobRequest | null {
  const innermost = dropTargets[0]
  const outermost = dropTargets[dropTargets.length - 1]
  if (!innermost || !outermost) return null
  if (!isColumnData(outermost.data)) return null

  const status = outermost.data.statusKey

  if (isJobCardData(innermost.data)) {
    if (innermost.data.jobId === source.jobId) return null
    return {
      jobId: source.jobId,
      status,
      anchorJobId: innermost.data.jobId,
      placement: extractClosestEdge(innermost.data) === 'top' ? 'above' : 'below',
    }
  }

  const lastJobId = outermost.data.lastJobId
  if (lastJobId === null || lastJobId === source.jobId) {
    // Nothing to anchor against: an empty destination column, so the server
    // assigns top priority. Releasing a column's only card back into its own
    // blank space would change nothing, so that is a no-op rather than a
    // pointless round trip that re-tops the card.
    if (status === source.statusKey) return null
    return { jobId: source.jobId, status }
  }

  return { jobId: source.jobId, status, anchorJobId: lastJobId, placement: 'below' }
}

export interface KanbanDragMonitor {
  /** The column currently under the pointer, for the drop highlight. */
  dragOverStatus: string | null
  setColumnDragOver: (statusKey: string, isOver: boolean) => void
  /**
   * True for exactly as long as a card is under the pointer. The board-wide
   * monitor is the only place that knows this — useJobCardDrag's isDragging
   * is per card, and asking six columns of cards whether any of them is
   * dragging is a second source of truth for one fact.
   *
   * A ref, not state: its reader is the reconciliation tick, which runs on a
   * timer rather than in a render, and publishing it as state would re-render
   * the whole board twice per gesture — including the draggable registrations
   * this file's header warns must not be rebuilt mid-drag.
   */
  isDraggingRef: React.RefObject<boolean>
}

export function useKanbanDragMonitor(
  onMove: (request: MoveJobRequest) => void,
  /**
   * Called once the drag ends with no move to follow — cancelled (Escape, or
   * a drop outside the board) or a no-op drop (resolveDrop returned null).
   * When a move DOES follow, onMove's caller settles movePendingRef and is
   * the release trigger instead; this and that are the two ways the drag/move
   * pause the reconciliation loop reads can end, so between them every
   * release is covered without this hook needing to know movePendingRef
   * exists.
   */
  onDragReleased: () => void,
): KanbanDragMonitor {
  const [dragOverStatus, setDragOverStatus] = useState<string | null>(null)
  const isDraggingRef = useRef(false)
  const onMoveRef = useRef(onMove)
  onMoveRef.current = onMove
  const onDragReleasedRef = useRef(onDragReleased)
  onDragReleasedRef.current = onDragReleased

  useEffect(
    () =>
      monitorForElements({
        canMonitor: ({ source }) => isJobCardData(source.data),
        onDragStart: () => {
          isDraggingRef.current = true
        },
        onDrop: ({ source, location }) => {
          // Cleared ahead of the two early returns below rather than after
          // onMove, so a cancelled drag (Escape, or a drop on nothing) also
          // releases the pause. Nothing can observe the gap before onMove
          // sets movePendingRef — this whole callback is one synchronous turn.
          isDraggingRef.current = false
          // Cleared globally rather than per column: Escape cancels a drag
          // without any drop target seeing a leave, which would otherwise
          // strand a highlighted column for the rest of the session.
          setDragOverStatus(null)
          const request = isJobCardData(source.data)
            ? resolveDrop(source.data, location.current.dropTargets)
            : null
          if (request) {
            onMoveRef.current(request)
            return
          }
          // No move follows, so nothing else closes the pause this gesture
          // opened: without this, a reconcile tick deferred by the drag
          // would sit idle until the next 30s poll instead of catching up
          // immediately. (The future SSE trigger enters through this same
          // callback.)
          onDragReleasedRef.current()
        },
      }),
    [],
  )

  const setColumnDragOver = useCallback((statusKey: string, isOver: boolean) => {
    // A leave from the old column can arrive after the enter into the new
    // one; only the column that owns the highlight may clear it.
    setDragOverStatus((current) => {
      if (isOver) return statusKey
      return current === statusKey ? null : current
    })
  }, [])

  return { dragOverStatus, setColumnDragOver, isDraggingRef }
}

export interface JobCardDrag {
  ref: React.RefObject<HTMLDivElement | null>
  isDragging: boolean
  /** True when the pending click is the tail of a drag and must not navigate. */
  shouldSuppressClick: () => boolean
}

export function useJobCardDrag(
  jobId: string,
  statusKey: string,
  movePendingRef: React.RefObject<boolean>,
): JobCardDrag {
  const ref = useRef<HTMLDivElement | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const draggedSincePointerDownRef = useRef(false)

  useEffect(() => {
    const element = ref.current
    if (!element) return undefined

    // Each press starts a fresh verdict; the drag, if one happens, overwrites
    // it before the click arrives. A timer-based version of this races the
    // click event, which is how "the card navigated instead of moving" bugs
    // come back.
    const onPointerDown = () => {
      draggedSincePointerDownRef.current = false
    }
    element.addEventListener('pointerdown', onPointerDown)

    const cleanup = combine(
      draggable({
        element,
        getInitialData: (): JobCardDragData => ({ type: JOB_CARD_TYPE, jobId, statusKey }),
        canDrag: () => !movePendingRef.current,
        onDragStart: () => {
          draggedSincePointerDownRef.current = true
          setIsDragging(true)
        },
        onDrop: () => setIsDragging(false),
      }),
      dropTargetForElements({
        element,
        canDrop: ({ source }) => isJobCardData(source.data),
        getData: ({ input, element: target }: ElementDropTargetGetFeedbackArgs) =>
          attachClosestEdge(
            { type: JOB_CARD_TYPE, jobId, statusKey },
            { input, element: target, allowedEdges: ['top', 'bottom'] },
          ),
      }),
    )

    return () => {
      element.removeEventListener('pointerdown', onPointerDown)
      cleanup()
    }
  }, [jobId, statusKey, movePendingRef])

  const shouldSuppressClick = useCallback(() => draggedSincePointerDownRef.current, [])

  return { ref, isDragging, shouldSuppressClick }
}

export function useColumnDropTarget(
  statusKey: string,
  lastJobId: string | null,
  setColumnDragOver: (statusKey: string, isOver: boolean) => void,
): React.RefObject<HTMLDivElement | null> {
  const ref = useRef<HTMLDivElement | null>(null)
  const lastJobIdRef = useRef(lastJobId)
  lastJobIdRef.current = lastJobId
  const setColumnDragOverRef = useRef(setColumnDragOver)
  setColumnDragOverRef.current = setColumnDragOver

  useEffect(() => {
    const element = ref.current
    if (!element) return undefined

    return combine(
      dropTargetForElements({
        element,
        canDrop: ({ source }) => isJobCardData(source.data),
        getData: (): ColumnDropData => ({
          type: COLUMN_TYPE,
          statusKey,
          lastJobId: lastJobIdRef.current,
        }),
        onDragEnter: () => setColumnDragOverRef.current(statusKey, true),
        onDragLeave: () => setColumnDragOverRef.current(statusKey, false),
        onDrop: () => setColumnDragOverRef.current(statusKey, false),
      }),
      // The columns are 90vh scrollers; without this a drag to a card below
      // the fold has nowhere to go.
      autoScrollForElements({
        element,
        canScroll: ({ source }) => isJobCardData(source.data),
      }),
    )
  }, [statusKey])

  return ref
}
