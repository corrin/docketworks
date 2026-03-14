import { ModuleRegistry, AllCommunityModule, themeQuartz } from 'ag-grid-community'
import type { ValueFormatterParams } from 'ag-grid-community'
import { formatCurrency, formatHoursDisplay } from '@/utils/string-formatting'

ModuleRegistry.registerModules([AllCommunityModule])

export const customTheme = themeQuartz.withParams({
  accentColor: '#4361EE',
  backgroundColor: '#FFFFFF',
  foregroundColor: '#1F2937',
  borderColor: 'rgba(0, 0, 0, 0.1)',
  headerBackgroundColor: 'rgba(67, 97, 238, 0.1)',
  oddRowBackgroundColor: 'rgba(0, 0, 0, 0.02)',
  spacing: 4,
})

export const defaultGridOptions = {
  theme: customTheme,

  rowSelection: {
    mode: 'singleRow',
    enableClickSelection: true,
  },

  animateRows: true,

  columnTypes: {
    dateColumn: {
      filter: 'agDateColumnFilter',
      filterParams: {
        comparator: (filterLocalDateAtMidnight: Date, cellValue: string) => {
          const dateAsString = cellValue
          if (dateAsString == null) return -1
          const dateParts = dateAsString.split('/')
          const cellDate = new Date(
            Number(dateParts[2]),
            Number(dateParts[1]) - 1,
            Number(dateParts[0]),
          )
          if (filterLocalDateAtMidnight.getTime() === cellDate.getTime()) {
            return 0
          }
          if (cellDate < filterLocalDateAtMidnight) {
            return -1
          }
          if (cellDate > filterLocalDateAtMidnight) {
            return 1
          }
          return 0
        },
      },
    },
    numericColumn: {
      filter: 'agNumberColumnFilter',
      cellClass: 'numeric-cell',
    },
    currencyColumn: {
      filter: 'agNumberColumnFilter',
      cellClass: 'numeric-cell currency-cell',
      valueFormatter: (params: ValueFormatterParams) => {
        if (params.value == null) return ''
        return formatCurrency(params.value)
      },
    },
    hoursColumn: {
      filter: 'agNumberColumnFilter',
      cellClass: 'numeric-cell hours-cell',
      valueFormatter: (params: ValueFormatterParams) => {
        if (params.value == null) return ''
        return formatHoursDisplay(Number(params.value))
      },
    },
  },

  defaultColDef: {
    flex: 1,
    minWidth: 100,
    resizable: true,
    sortable: true,
    filter: true,
    editable: false,
  },

  pagination: false,

  rowHeight: 50,
  headerHeight: 45,

  rowClass: 'timesheet-row',

  loadingOverlayComponent: null,
  noRowsOverlayComponent: null,
}

export const timesheetGridClasses = {
  wrapper: 'timesheet-grid',
  container: 'h-full w-full',
}
