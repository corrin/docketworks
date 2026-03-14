import type { ICellEditor, ICellEditorParams } from 'ag-grid-community'

interface RateOption {
  value: string
  label: string
  color: string
}

const RATE_OPTIONS: RateOption[] = [
  { value: 'Ord', label: 'Ord', color: '#374151' },
  { value: '1.5', label: '1.5x', color: '#D97706' },
  { value: '2.0', label: '2.0x', color: '#DC2626' },
  { value: 'Unpaid', label: 'Unpaid', color: '#6B7280' },
]

export class TimesheetEntryRateCellEditor implements ICellEditor {
  private value: string = 'Ord'
  private params!: ICellEditorParams
  private container!: HTMLDivElement
  private dropdown!: HTMLDivElement
  private highlightedIndex: number = 0

  init(params: ICellEditorParams): void {
    this.value = params.value || 'Ord'
    this.params = params
    this.highlightedIndex = RATE_OPTIONS.findIndex((opt) => opt.value === this.value)
    if (this.highlightedIndex === -1) this.highlightedIndex = 0

    this.createUI()
    this.setupEventListeners()
  }

  private createUI(): void {
    this.container = document.createElement('div')
    this.container.className = 'rate-cell-editor-container'
    this.container.setAttribute('data-automation-id', 'TimesheetEntryRateCellEditor-container')
    this.container.style.cssText = `
      position: relative;
      width: 100%;
      height: 100%;
    `

    this.dropdown = document.createElement('div')
    this.dropdown.className = 'rate-dropdown'
    this.dropdown.setAttribute('data-automation-id', 'TimesheetEntryRateCellEditor-dropdown')
    this.dropdown.style.cssText = `
      position: fixed;
      background: white;
      border: 1px solid #E5E7EB;
      border-radius: 6px;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
      z-index: 10000;
      min-width: 100px;
      overflow: hidden;
    `

    this.renderOptions()
    this.container.appendChild(this.dropdown)

    // Position the dropdown after it's added to DOM
    setTimeout(() => this.positionDropdown(), 0)
  }

  private positionDropdown(): void {
    const cellRect = this.params.eGridCell?.getBoundingClientRect()
    if (cellRect) {
      this.dropdown.style.top = `${cellRect.bottom}px`
      this.dropdown.style.left = `${cellRect.left}px`
      this.dropdown.style.minWidth = `${cellRect.width}px`
    }
  }

  private renderOptions(): void {
    this.dropdown.innerHTML = ''

    RATE_OPTIONS.forEach((option, index) => {
      const item = document.createElement('div')
      item.className = 'rate-dropdown-item'
      item.dataset.index = String(index)
      item.setAttribute('data-automation-id', `TimesheetEntryRateCellEditor-option-${option.value}`)

      item.innerHTML = `
        <span style="color: ${option.color}; font-weight: 500;">${option.label}</span>
      `

      item.style.cssText = `
        padding: 8px 12px;
        cursor: pointer;
        transition: background-color 0.15s ease;
        ${index === this.highlightedIndex ? 'background-color: #F3F4F6;' : ''}
      `

      item.addEventListener('mouseenter', () => {
        this.highlightedIndex = index
        this.updateHighlight()
      })

      item.addEventListener('click', () => {
        this.selectOption(option)
      })

      this.dropdown.appendChild(item)
    })
  }

  private updateHighlight(): void {
    const items = this.dropdown.querySelectorAll('.rate-dropdown-item')
    items.forEach((item, index) => {
      const el = item as HTMLElement
      el.style.backgroundColor = index === this.highlightedIndex ? '#F3F4F6' : ''
    })
  }

  private selectOption(option: RateOption): void {
    this.value = option.value
    this.params.stopEditing()
  }

  private setupEventListeners(): void {
    this.container.addEventListener('keydown', (e: KeyboardEvent) => {
      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault()
          this.highlightedIndex = Math.min(this.highlightedIndex + 1, RATE_OPTIONS.length - 1)
          this.updateHighlight()
          break
        case 'ArrowUp':
          e.preventDefault()
          this.highlightedIndex = Math.max(this.highlightedIndex - 1, 0)
          this.updateHighlight()
          break
        case 'Enter':
          e.preventDefault()
          if (this.highlightedIndex >= 0 && this.highlightedIndex < RATE_OPTIONS.length) {
            this.selectOption(RATE_OPTIONS[this.highlightedIndex])
          }
          break
        case 'Escape':
          e.preventDefault()
          this.params.stopEditing()
          break
      }
    })
  }

  getGui(): HTMLElement {
    return this.container
  }

  getValue(): string {
    return this.value
  }

  isPopup(): boolean {
    return true
  }

  afterGuiAttached(): void {
    this.container.focus()
    this.positionDropdown()
  }
}
