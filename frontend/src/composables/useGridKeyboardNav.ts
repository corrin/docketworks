/**
 * useGridKeyboardNav - Keyboard navigation and shortcuts for spreadsheet-like tables.
 *
 * Scope:
 * - Does not depend on any specific table lib; caller wires events and selection state.
 * - Emits high-level intents via provided callbacks. Caller performs actual mutations.
 *
 * Supported shortcuts (platform-aware):
 * - Enter / F2: start edit
 * - Enter (when editing): confirm edit (commit)
 * - Esc: cancel edit
 * - Tab / Shift+Tab: move focus horizontally (delegate to browser / optional callback)
 * - ArrowUp / ArrowDown: move selection between rows
 * - Ctrl/Cmd + Enter: add line below
 * - Ctrl/Cmd + D: duplicate selected line
 * - Ctrl/Cmd + Backspace: delete selected line
 * - Alt + ArrowUp/ArrowDown: move selected row up/down (when manual ordering is supported)
 *
 * Usage:
 * const { onKeydown } = useGridKeyboardNav({
 *   getRowCount, getSelectedIndex, setSelectedIndex,
 *   startEdit, commitEdit, cancelEdit,
 *   addLine, duplicateSelected, deleteSelected,
 *   moveSelectedUp, moveSelectedDown,
 *   moveCellLeft, moveCellRight,
 * })
 * bind onKeydown to a focusable wrapper: <div tabindex="0" @keydown="onKeydown">...</div>
 */

export type EditIntent = 'start' | 'commit' | 'cancel'

interface Options {
  // Selection state
  getRowCount: () => number
  getSelectedIndex: () => number
  setSelectedIndex: (index: number) => void

  // Editing lifecycle
  startEdit?: () => void
  commitEdit?: () => void
  cancelEdit?: () => void

  // Row operations
  addLine?: () => void
  duplicateSelected?: () => void
  deleteSelected?: () => void
  moveSelectedUp?: () => void
  moveSelectedDown?: () => void

  // Optional cell navigation hooks (if you implement per-cell focus)
  moveCellLeft?: () => void
  moveCellRight?: () => void
}

export type GridFocusTarget =
  | { kind: 'relativeCell'; delta: 1 | -1 }
  | { kind: 'sameColumnNextRow' }
  | { kind: 'column'; rowIndex: number; columnId: string }

export type GridCellKeydownOptions = {
  container: HTMLElement | null
  rowIndex: number
  columnId: string
  tabTarget?: GridFocusTarget
  enterTarget?: GridFocusTarget
}

function isMac(): boolean {
  if (typeof navigator === 'undefined') return false
  return /Mac|iPod|iPhone|iPad/.test(navigator.platform)
}

export function gridCellAttrs(rowIndex: number, columnId: string) {
  return {
    'data-grid-nav-cell': 'true',
    'data-grid-row': String(rowIndex),
    'data-grid-col': columnId,
  }
}

function getNavigableCells(container: HTMLElement): HTMLElement[] {
  return Array.from(
    container.querySelectorAll<HTMLElement>(
      '[data-grid-nav-cell="true"]:not([disabled]):not([aria-disabled="true"])',
    ),
  )
}

function isNavigableCell(element: HTMLElement): boolean {
  if (element.hasAttribute('disabled')) return false
  if (element.getAttribute('aria-disabled') === 'true') return false
  return true
}

function isNumericGridInput(element: HTMLElement): element is HTMLInputElement {
  if (!(element instanceof HTMLInputElement)) return false
  if (element.type === 'number') return true
  if (element.inputMode === 'decimal') return true
  return element.classList.contains('numeric-input')
}

function focusElement(element: Element | null): boolean {
  if (!(element instanceof HTMLElement)) return false
  element.focus()
  return document.activeElement === element
}

function focusGridDestination(element: Element | null): void {
  if (!focusElement(element)) return
  if (!(element instanceof HTMLElement)) return
  if (isNumericGridInput(element)) element.select()
}

export function handleGridCellKeydown(e: KeyboardEvent, opts: GridCellKeydownOptions): boolean {
  if (!(e.currentTarget instanceof HTMLElement)) return false
  const target = e.currentTarget

  function focusTarget(focusTarget: GridFocusTarget): void {
    const container = opts.container
    if (!container) return

    if (focusTarget.kind === 'relativeCell') {
      const cells = getNavigableCells(container)
      const idx = cells.indexOf(target)
      if (idx < 0) return
      const next = cells[idx + focusTarget.delta]
      if (next) window.setTimeout(() => focusGridDestination(next), 0)
      return
    }

    const rowIndex =
      focusTarget.kind === 'sameColumnNextRow' ? opts.rowIndex + 1 : focusTarget.rowIndex
    const columnId = focusTarget.kind === 'sameColumnNextRow' ? opts.columnId : focusTarget.columnId
    const selector = `[data-grid-nav-cell="true"][data-grid-row="${rowIndex}"][data-grid-col="${columnId}"]:not([disabled]):not([aria-disabled="true"])`
    window.setTimeout(() => {
      const next = container.querySelector(selector)
      if (next instanceof HTMLElement && isNavigableCell(next)) focusGridDestination(next)
    }, 0)
  }

  if (e.key === 'Tab') {
    e.preventDefault()
    target.blur()
    focusTarget(opts.tabTarget ?? { kind: 'relativeCell', delta: e.shiftKey ? -1 : 1 })
    return true
  }

  if (e.key === 'Enter') {
    if (e.shiftKey && target instanceof HTMLTextAreaElement) return false
    if (e.metaKey || e.ctrlKey || e.altKey) return false
    e.preventDefault()
    target.blur()
    focusTarget(opts.enterTarget ?? { kind: 'sameColumnNextRow' })
    return true
  }

  return false
}

export function useGridKeyboardNav(opts: Options) {
  const platformIsMac = isMac()

  function clamp(val: number, min: number, max: number): number {
    return Math.max(min, Math.min(max, val))
  }

  function selectDelta(delta: number) {
    const count = opts.getRowCount()
    if (count <= 0) return
    const next = clamp(opts.getSelectedIndex() + delta, 0, count - 1)
    opts.setSelectedIndex(next)
  }

  function onKeydown(e: KeyboardEvent) {
    const ctrlOrCmd = platformIsMac ? e.metaKey : e.ctrlKey

    switch (e.key) {
      case 'F2':
        if (opts.startEdit) {
          e.preventDefault()
          opts.startEdit()
        }
        return
      case 'Enter':
        // Ctrl/Cmd+Enter: add line
        if (ctrlOrCmd) {
          if (opts.addLine) {
            e.preventDefault()
            opts.addLine()
          }
          return
        }
        // Plain Enter: start or commit edit
        if (opts.commitEdit) {
          e.preventDefault()
          opts.commitEdit()
        } else if (opts.startEdit) {
          e.preventDefault()
          opts.startEdit()
        }
        return
      case 'Escape':
        if (opts.cancelEdit) {
          e.preventDefault()
          opts.cancelEdit()
        }
        return
      case 'Tab':
        if (!e.shiftKey && opts.moveCellRight) {
          e.preventDefault()
          opts.moveCellRight()
          return
        }
        if (e.shiftKey && opts.moveCellLeft) {
          e.preventDefault()
          opts.moveCellLeft()
          return
        }
        return
      case 'ArrowUp':
        if (e.altKey) {
          if (opts.moveSelectedUp) {
            e.preventDefault()
            opts.moveSelectedUp()
          }
          return
        }
        e.preventDefault()
        selectDelta(-1)
        return
      case 'ArrowDown':
        if (e.altKey) {
          if (opts.moveSelectedDown) {
            e.preventDefault()
            opts.moveSelectedDown()
          }
          return
        }
        e.preventDefault()
        selectDelta(1)
        return
      case 'Backspace':
        if (ctrlOrCmd) {
          if (opts.deleteSelected) {
            e.preventDefault()
            opts.deleteSelected()
          }
        }
        return
      case 'd':
      case 'D':
        if (ctrlOrCmd && opts.duplicateSelected) {
          e.preventDefault()
          opts.duplicateSelected()
        }
        return
      default:
        return
    }
  }

  return {
    onKeydown,
  }
}
