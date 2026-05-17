import { describe, expect, it, vi } from 'vitest'
import { gridCellAttrs, handleGridCellKeydown } from '@/composables/useGridKeyboardNav'

function makeInput(rowIndex: number, columnId: string): HTMLInputElement {
  const input = document.createElement('input')
  Object.entries(gridCellAttrs(rowIndex, columnId)).forEach(([key, value]) => {
    input.setAttribute(key, value)
  })
  return input
}

describe('useGridKeyboardNav cell navigation', () => {
  it('Tab moves to the next editable cell', async () => {
    vi.useFakeTimers()
    const container = document.createElement('div')
    const first = makeInput(0, 'desc')
    const second = makeInput(0, 'quantity')
    container.append(first, second)
    document.body.append(container)
    first.focus()

    const event = new KeyboardEvent('keydown', {
      key: 'Tab',
      bubbles: true,
      cancelable: true,
    })
    Object.defineProperty(event, 'currentTarget', { value: first })

    const handled = handleGridCellKeydown(event, {
      container,
      rowIndex: 0,
      columnId: 'desc',
    })

    await vi.runOnlyPendingTimersAsync()

    expect(handled).toBe(true)
    expect(event.defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(second)
    container.remove()
    vi.useRealTimers()
  })

  it('Shift+Tab moves to the previous editable cell', async () => {
    vi.useFakeTimers()
    const container = document.createElement('div')
    const first = makeInput(0, 'desc')
    const second = makeInput(0, 'quantity')
    container.append(first, second)
    document.body.append(container)
    second.focus()

    const event = new KeyboardEvent('keydown', {
      key: 'Tab',
      shiftKey: true,
      bubbles: true,
      cancelable: true,
    })
    Object.defineProperty(event, 'currentTarget', { value: second })

    const handled = handleGridCellKeydown(event, {
      container,
      rowIndex: 0,
      columnId: 'quantity',
    })

    await vi.runOnlyPendingTimersAsync()

    expect(handled).toBe(true)
    expect(event.defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(first)
    container.remove()
    vi.useRealTimers()
  })

  it('Tab skips disabled cells', async () => {
    vi.useFakeTimers()
    const container = document.createElement('div')
    const first = makeInput(0, 'desc')
    const disabled = makeInput(0, 'quantity')
    const third = makeInput(0, 'unit_cost')
    disabled.disabled = true
    container.append(first, disabled, third)
    document.body.append(container)
    first.focus()

    const event = new KeyboardEvent('keydown', {
      key: 'Tab',
      bubbles: true,
      cancelable: true,
    })
    Object.defineProperty(event, 'currentTarget', { value: first })

    const handled = handleGridCellKeydown(event, {
      container,
      rowIndex: 0,
      columnId: 'desc',
    })

    await vi.runOnlyPendingTimersAsync()

    expect(handled).toBe(true)
    expect(document.activeElement).toBe(third)
    container.remove()
    vi.useRealTimers()
  })

  it('Enter moves to the same column in the next row', async () => {
    vi.useFakeTimers()
    const container = document.createElement('div')
    const first = makeInput(0, 'quantity')
    const sameColumnNextRow = makeInput(1, 'quantity')
    const otherColumnNextRow = makeInput(1, 'unit_cost')
    container.append(first, otherColumnNextRow, sameColumnNextRow)
    document.body.append(container)
    first.focus()

    const event = new KeyboardEvent('keydown', {
      key: 'Enter',
      bubbles: true,
      cancelable: true,
    })
    Object.defineProperty(event, 'currentTarget', { value: first })

    const handled = handleGridCellKeydown(event, {
      container,
      rowIndex: 0,
      columnId: 'quantity',
    })

    await vi.runOnlyPendingTimersAsync()

    expect(handled).toBe(true)
    expect(event.defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(sameColumnNextRow)
    container.remove()
    vi.useRealTimers()
  })

  it('Shift+Enter leaves textarea newline handling alone', () => {
    const container = document.createElement('div')
    const textarea = document.createElement('textarea')
    Object.entries(gridCellAttrs(0, 'desc')).forEach(([key, value]) => {
      textarea.setAttribute(key, value)
    })
    container.append(textarea)

    const event = new KeyboardEvent('keydown', {
      key: 'Enter',
      shiftKey: true,
      bubbles: true,
      cancelable: true,
    })
    Object.defineProperty(event, 'currentTarget', { value: textarea })

    const handled = handleGridCellKeydown(event, {
      container,
      rowIndex: 0,
      columnId: 'desc',
    })

    expect(handled).toBe(false)
    expect(event.defaultPrevented).toBe(false)
  })

  it('missing next Enter target blurs without throwing', async () => {
    vi.useFakeTimers()
    const container = document.createElement('div')
    const first = makeInput(0, 'quantity')
    container.append(first)
    document.body.append(container)
    first.focus()

    const event = new KeyboardEvent('keydown', {
      key: 'Enter',
      bubbles: true,
      cancelable: true,
    })
    Object.defineProperty(event, 'currentTarget', { value: first })

    const handled = handleGridCellKeydown(event, {
      container,
      rowIndex: 0,
      columnId: 'quantity',
    })

    await vi.runOnlyPendingTimersAsync()

    expect(handled).toBe(true)
    expect(event.defaultPrevented).toBe(true)
    expect(document.activeElement).not.toBe(first)
    container.remove()
    vi.useRealTimers()
  })
})
