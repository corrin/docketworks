/**
 * Keyboard shortcuts for timesheet entry grid
 * Pure UI constants - can be changed without backend modifications
 */

export interface KeyboardShortcut {
  key: string
  description: string
  action: string
}

export const KEYBOARD_SHORTCUTS: KeyboardShortcut[] = [
  { key: 'Tab', description: 'Move to next cell', action: 'navigate' },
  { key: 'Shift+Tab', description: 'Move to previous cell', action: 'navigate' },
  { key: 'Enter', description: 'Save cell and move down', action: 'save-move' },
  { key: 'Escape', description: 'Cancel editing', action: 'cancel' },
  { key: 'F2', description: 'Enter edit mode', action: 'edit' },
  { key: 'Ctrl+S', description: 'Save all changes', action: 'save-all' },
  { key: 'Ctrl+N', description: 'Add new row', action: 'add-row' },
  { key: 'Delete', description: 'Delete selected row', action: 'delete' },
]
