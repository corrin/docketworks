import { useEffect, useRef, useState } from 'react'

/**
 * The draft/phantom row state machine shared by the editable grids
 * (CostLineGrid, SmartTimesheetTable). Extracted mechanically from
 * CostLineGrid; the behavioural comments below travelled with the code
 * because each states a constraint that was learned the hard way.
 *
 * Invariant: exactly one trailing empty phantom draft. The moment the
 * phantom stops being empty it becomes an ordinary draft and a fresh
 * phantom is appended behind it. Draft identity is the localId, never the
 * array index: an index-keyed row remounts (and drops focus) when its
 * position shifts during a save.
 */

export interface DraftEntry<TDraft> {
  localId: string
  draft: TDraft
}

/**
 * The structural slice of a React FocusEvent the row-exit check reads.
 * Declared structurally so tests can hand-build events without casts.
 */
export interface RowExitBlurEvent {
  currentTarget: { contains(other: Element | null): boolean }
  relatedTarget: Element | null
}

export interface UseDraftRowsOptions<TDraft> {
  emptyDraft: () => TDraft
  draftIsEmpty: (draft: TDraft) => boolean
  /** Whether the draft has enough content to POST (the caller's readiness rule). */
  isReady: (draft: TDraft) => boolean
  /** POST the draft. Exactly one of the callbacks must eventually fire. */
  persist: (draft: TDraft, callbacks: { onCreated: () => void; onFailed: () => void }) => void
  /** Fires after a successful persist removed the draft (focus handoff hook). */
  onCreated?: (localId: string) => void
}

export interface DraftRowsApi<TDraft> {
  drafts: DraftEntry<TDraft>[]
  updateDraft: (localId: string, patch: Partial<TDraft>) => void
  /** Persist-if-ready; safe under StrictMode double-invocation and double-fires. */
  commitDraft: (localId: string) => void
  removeDraft: (localId: string) => void
  isPhantom: (localId: string) => boolean
  isPersisting: (localId: string) => boolean
  anyPersisting: boolean
  isFailed: (localId: string) => boolean
  /** Row-level blur/focus wiring: focus leaving the whole row commits the draft. */
  rowExitHandlers: (localId: string) => {
    onBlur: (event: RowExitBlurEvent) => void
    onFocus: () => void
  }
  /**
   * For persists the hook does not own (e.g. stock consumption, where the
   * server creates the row): raises the in-flight guard, kills any pending
   * row-exit commit, and returns the draft — or null when the row is missing
   * or already persisting.
   */
  beginExternalPersist: (localId: string) => TDraft | null
  settleExternalPersist: (localId: string, outcome: 'created' | 'failed') => void
}

export function useDraftRows<TDraft>(options: UseDraftRowsOptions<TDraft>): DraftRowsApi<TDraft> {
  const freshPhantom = (): DraftEntry<TDraft> => ({
    localId: crypto.randomUUID(),
    draft: options.emptyDraft(),
  })
  const [drafts, setDrafts] = useState<DraftEntry<TDraft>[]>(() => [freshPhantom()])
  // Draft rows whose last persist attempt failed wear a failure badge until an
  // attempt lands (the E2E asserts the exact text on the row).
  const [failedIds, setFailedIds] = useState<ReadonlySet<string>>(new Set())
  const markFailed = (localId: string) => setFailedIds((current) => new Set(current).add(localId))
  const clearFailed = (localId: string) =>
    setFailedIds((current) => {
      if (!current.has(localId)) return current
      const next = new Set(current)
      next.delete(localId)
      return next
    })
  // Ref for the synchronous double-POST guard; state so cells can render a
  // draft's inputs disabled while its persist is in flight (edits made during
  // the flight would be silently dropped when the draft row is replaced).
  const persistingRef = useRef<Set<string>>(new Set())
  const [persistingIds, setPersistingIds] = useState<ReadonlySet<string>>(new Set())
  const syncPersisting = () => setPersistingIds(new Set(persistingRef.current))
  // Row exit is DEFERRED by a 0ms timer: a row's own portalled popover is a
  // DOM child of body, so a relatedTarget containment check would read
  // opening it as leaving the row. Focus landing anywhere in the row's REACT
  // tree (portals included — React bubbles their focus events) cancels the
  // pending commit; only a genuine exit lets it fire.
  const rowExitTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())
  // Unmounting with a pending row-exit timer must not fire a POST against a
  // grid that no longer exists (e.g. the user navigated tabs mid-blur).
  useEffect(() => {
    const timers = rowExitTimersRef.current
    return () => {
      for (const timer of timers.values()) clearTimeout(timer)
      timers.clear()
    }
  }, [])
  const cancelRowExitCommit = (localId: string) => {
    const timer = rowExitTimersRef.current.get(localId)
    if (timer !== undefined) {
      clearTimeout(timer)
      rowExitTimersRef.current.delete(localId)
    }
  }
  const scheduleRowExitCommit = (localId: string) => {
    cancelRowExitCommit(localId)
    rowExitTimersRef.current.set(
      localId,
      setTimeout(() => {
        rowExitTimersRef.current.delete(localId)
        commitDraft(localId)
      }, 0),
    )
  }

  const settlePersisted = (localId: string) => {
    setDrafts((current) => {
      // The guard entry clears inside the same updater that removes the
      // draft, so no replay can see the row without its guard.
      persistingRef.current.delete(localId)
      const remaining = current.filter((candidate) => candidate.localId !== localId)
      return remaining.length ? remaining : [freshPhantom()]
    })
    // Also clear eagerly: React only runs the updater above at render time,
    // and the persisting snapshot below must not carry a settled row into
    // the next frame (anyPersisting gates the next phantom's inputs).
    persistingRef.current.delete(localId)
    clearFailed(localId)
    syncPersisting()
    options.onCreated?.(localId)
  }

  const settleFailed = (localId: string) => {
    // The draft survives for a retry; without this delete the guard would
    // silently discard every later commit on the row.
    persistingRef.current.delete(localId)
    markFailed(localId)
    syncPersisting()
  }

  const persistDraftIfReady = (currentDrafts: DraftEntry<TDraft>[], localId: string) => {
    const entry = currentDrafts.find((candidate) => candidate.localId === localId)
    if (!entry) return
    if (!options.isReady(entry.draft)) return
    if (persistingRef.current.has(localId)) return
    persistingRef.current.add(localId)
    syncPersisting()
    options.persist(entry.draft, {
      onCreated: () => settlePersisted(localId),
      onFailed: () => settleFailed(localId),
    })
  }

  const commitDraft = (localId: string) => {
    // Inside the updater so it observes the same render's updateDraft; the
    // persisting-set guard makes StrictMode's double invocation harmless.
    setDrafts((current) => {
      persistDraftIfReady(current, localId)
      return current
    })
  }

  return {
    drafts,
    updateDraft: (localId, patch) => {
      setDrafts((current) => {
        const next = current.map((entry) =>
          entry.localId === localId ? { ...entry, draft: { ...entry.draft, ...patch } } : entry,
        )
        const last = next.at(-1)
        if (last && !options.draftIsEmpty(last.draft)) {
          next.push(freshPhantom())
        }
        return next
      })
    },
    commitDraft,
    removeDraft: (localId) => {
      setDrafts((current) => {
        const remaining = current.filter((entry) => entry.localId !== localId)
        return remaining.length ? remaining : [freshPhantom()]
      })
      clearFailed(localId)
    },
    isPhantom: (localId) => drafts.at(-1)?.localId === localId,
    isPersisting: (localId) => persistingIds.has(localId),
    anyPersisting: persistingIds.size > 0,
    isFailed: (localId) => failedIds.has(localId),
    rowExitHandlers: (localId) => ({
      onBlur: (event) => {
        // Focus leaving the whole ROW is the persist gesture for typed
        // drafts. In-row moves never schedule; for the rest the deferred
        // timer lets focus landing back in the row's React tree cancel
        // before the commit fires.
        if (event.currentTarget.contains(event.relatedTarget)) return
        scheduleRowExitCommit(localId)
      },
      onFocus: () => cancelRowExitCommit(localId),
    }),
    beginExternalPersist: (localId) => {
      const entry = drafts.find((candidate) => candidate.localId === localId)
      if (!entry) return null
      if (persistingRef.current.has(localId)) return null
      // The guard goes up BEFORE the request and the pending row-exit timer
      // dies: focus leaving the row after an external pick must not also
      // POST the typed draft beside the externally created line.
      persistingRef.current.add(localId)
      syncPersisting()
      cancelRowExitCommit(localId)
      return entry.draft
    },
    settleExternalPersist: (localId, outcome) => {
      if (outcome === 'created') {
        settlePersisted(localId)
      } else {
        settleFailed(localId)
      }
    },
  }
}
