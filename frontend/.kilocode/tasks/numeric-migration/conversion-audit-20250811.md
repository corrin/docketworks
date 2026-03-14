# Numeric Conversions Report - Mon Aug 11 21:17:26 -03 2025

## parseFloat() Occurrences

src/components/job/CostLineAdjustmentModal.vue:207: formData.value.unit_cost = parseFloat(input)
src/components/job/CostLineAdjustmentModal.vue:217: formData.value.unit_rev = parseFloat(input)
src/components/job/CostLineMaterialModal.vue:192: form.value.unitCost = parseFloat(input)
src/components/job/CostLineMaterialModal.vue:202: form.value.unitRevenue = parseFloat(input)
src/components/job/CostLineTimeModal.vue:131: form.value.hours = parseFloat(input)
src/components/job/SimpleTotalTable.vue:45: const numericValue = parseFloat(inputValue.value)
src/views/JobCreateView.vue:285: const sanitizedValue = parseFloat(target.value)
src/views/JobCreateView.vue:295: const sanitizedValue = parseFloat(target.value)

## parseInt() Occurrences

src/components/kpi/MonthSelector.vue:101: emit('update:year', parseInt(year))
src/components/kpi/MonthSelector.vue:102: emit('update:month', parseInt(month))
src/views/TimesheetEntryView.vue:572: const year = parseInt(parts[0], 10)
src/views/TimesheetEntryView.vue:573: const month = parseInt(parts[1], 10) - 1
src/views/TimesheetEntryView.vue:574: const day = parseInt(parts[2], 10)
src/views/TimesheetEntryView.vue:636: const year = parseInt(parts[0], 10)
src/views/TimesheetEntryView.vue:637: const month = parseInt(parts[1], 10) - 1
src/views/TimesheetEntryView.vue:638: const day = parseInt(parts[2], 10)
src/views/TimesheetEntryView.vue:654: const year = parseInt(parts[0], 10)
src/views/TimesheetEntryView.vue:655: const month = parseInt(parts[1], 10) - 1
src/views/TimesheetEntryView.vue:656: const day = parseInt(parts[2], 10)

## Number() Occurrences

src/components/job/JobActualTab.vue:130: {{ formatNumber(line.quantity) }}
src/components/job/JobActualTab.vue:332:function formatNumber(value: number | undefined): string {
src/components/job/JobCostAnalysisTab.vue:98: <td class="py-2 px-4 text-center">{{ formatNumber(estimate.hours) }}</td>
src/components/job/JobCostAnalysisTab.vue:100: {{ formatNumber(quote.hours) }}
src/components/job/JobCostAnalysisTab.vue:104: {{ formatNumber(actual.hours) }}
src/components/job/JobCostAnalysisTab.vue:346:function formatNumber(value: number): string {
src/components/job/JobQuoteTab.vue:286: {{ formatNumber(revision.summary.hours) }}h
src/components/job/JobQuoteTab.vue:322: <span class="font-medium">{{ formatNumber(line.quantity) }}</span>
src/components/job/JobQuoteTab.vue:819:function formatNumber(value: number): string {
src/components/purchasing/DeliveryReceiptLinesTable.vue:198: h('span', { class: 'font-bold' }, Number(line.quantity) || 0),
src/components/purchasing/DeliveryReceiptLinesTable.vue:203: h('span', {}, Number(line.received_quantity) || 0),
src/components/purchasing/PoLinesTable.vue:212: const num = Number(val)
src/components/purchasing/PoLinesTable.vue:237: const cost = val === '' ? null : Number(val)
src/components/purchasing/PoLinesTable.vue:252: (row.original.unit_cost !== null && Number(row.original.unit_cost) > 0) || props.readOnly,
src/components/purchasing/ReceivedItemsTable.vue:135: const num = Number(val)
src/components/purchasing/ReceivedItemsTable.vue:197: const num = Number(val)
src/components/purchasing/ReceivedItemsTable.vue:237: const num = Number(val)
src/components/quote/QuoteCostLinesGrid.vue:110: {{ formatNumber(line.quantity) }}
src/components/quote/QuoteCostLinesGrid.vue:149:function formatNumber(value: number): string {
src/components/quote/QuoteSummaryCard.vue:129: {{ formatNumber(quoteData.summary.hours) }} hrs
src/components/quote/QuoteSummaryCard.vue:576:function formatNumber(value: number): string {
src/components/shared/CostLinesGrid.vue:121: {{ formatNumber(line.quantity)
src/components/shared/CostLinesGrid.vue:215:function formatNumber(value: number | undefined): string {
src/components/shared/CostSetSummaryCard.vue:105:                >{{ formatNumber(typedSummary.hours) }} hrs</span
src/components/shared/CostSetSummaryCard.vue:250:function formatNumber(value: number): string {
src/components/StaffFormModal.vue:477: .map((g) => Number(g.trim()))
src/components/StaffFormModal.vue:484: .map((p) => Number(p.trim()))
src/components/timesheet/WeekPickerModal.vue:151: return getWeekNumber(date)
src/components/timesheet/WeekPickerModal.vue:210:function getWeekNumber(date: Date): number {
src/plugins/ag-grid.ts:35: Number(dateParts[2]),
src/plugins/ag-grid.ts:36: Number(dateParts[1]) - 1,
src/plugins/ag-grid.ts:37: Number(dateParts[0]),
src/plugins/ag-grid.ts:72: return `${Number(params.value).toFixed(2)}h`
src/services/date.service.ts:148: getDayNumber(dateString: string): string {
src/services/date.service.ts:184: number: this.getDayNumber(date),
src/services/date.service.ts:213:export const getDayNumber = (dateString: string) => dateService.getDayNumber(dateString)
src/utils/safetyUtils.ts:21:export function getSafeNumber(value: number | undefined, defaultValue: number = 0): number {
src/views/AdminMonthEnd.vue:164: <span class="font-mono text-sm">{{ jobNumber(id) }}</span>
src/views/AdminMonthEnd.vue:268:function jobNumber(id: string) {
src/views/WeeklyTimesheetView.vue:266: short: dateService.getDayNumber(d),
src/views/WeeklyTimesheetView.vue:274: short: dateService.getDayNumber(d),

## toString() Occurrences

src/components/kpi/MonthSelector.vue:43:const selectedValue = computed(() => `${props.year}-${props.month.toString().padStart(2, '0')}`)
src/components/kpi/MonthSelector.vue:89: const value = `${year}-${month.toString().padStart(2, '0')}`
src/components/purchasing/JobSelect.vue:139: const numberMatch = job.number?.toString().toLowerCase().includes(term)
src/components/purchasing/JobSelect.vue:140: const jobNumberMatch = job.job_number?.toString().toLowerCase().includes(term)
src/components/purchasing/PurchaseOrderJobCellEditor.ts:165: item.dataset.index = index.toString()
src/components/timesheet/WeeklyMetricsModal.vue:416: (job as Record<string, number>).job_number.toString().toLowerCase().includes(query) ||
src/components/ui/calendar/Calendar.vue:52: <CalendarGrid v-for="month in grid" :key="month.value.toString()">
src/components/ui/calendar/Calendar.vue:68: :key="weekDate.toString()"
src/components/ui/range-calendar/RangeCalendar.vue:51: <RangeCalendarGrid v-for="month in grid" :key="month.value.toString()">
src/components/ui/range-calendar/RangeCalendar.vue:67: :key="weekDate.toString()"
src/composables/useKanban.ts:243: job.job_number.toString().toLowerCase().includes(query) ||
src/services/aiProviderService.ts:45: params: { id: id.toString() },
src/services/aiProviderService.ts:55: await api.api_workflow_ai_providers_destroy(undefined, { params: { id: id.toString() } })
src/services/aiProviderService.ts:64: return await api.api_workflow_ai_providers_retrieve({ params: { id: id.toString() } })
src/services/aiProviderService.ts:74: params: { id: id.toString() },
src/services/job-aging-report.service.ts:52: const queryString = searchParams.toString()
src/services/quote-chat.service.ts:69: \_id: message.id?.toString() || '',
src/services/staff-performance-report.service.ts:28: const url = `/accounting/api/reports/staff-performance-summary/?${searchParams.toString()}`
src/services/staff-performance-report.service.ts:46: const url = `/accounting/api/reports/staff-performance/${staffId}/?${searchParams.toString()}`
