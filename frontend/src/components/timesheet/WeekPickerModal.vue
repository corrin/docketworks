<template>
  <Dialog :open="isOpen" @update:open="closeModal">
    <DialogContent class="max-w-md max-h-[90vh] overflow-y-auto">
      <div class="flex items-center justify-between mb-6">
        <h3 class="text-lg font-bold text-gray-900">📅 Select Week</h3>
        <button @click="closeModal" class="text-gray-400 hover:text-gray-600 transition-colors">
          <X class="w-5 h-5" />
        </button>
      </div>

      <div class="bg-blue-50 p-4 rounded-lg mb-6">
        <p class="text-sm text-blue-600 mb-1">Selected Week</p>
        <p class="font-semibold text-blue-900">
          {{ formatWeekRange(selectedWeekStart, selectedWeekEnd) }}
        </p>
        <p class="text-xs text-blue-600">Week {{ weekNumber }} of {{ year }}</p>
      </div>

      <div class="space-y-4">
        <div class="flex items-center justify-between mb-4">
          <button
            @click="previousMonth"
            class="p-2 text-gray-400 hover:text-gray-600 transition-colors"
          >
            <ChevronLeft class="w-5 h-5" />
          </button>

          <h4 class="text-lg font-semibold text-gray-900">
            {{ currentMonthYear }}
          </h4>

          <button
            @click="nextMonth"
            class="p-2 text-gray-400 hover:text-gray-600 transition-colors"
          >
            <ChevronRight class="w-5 h-5" />
          </button>
        </div>

        <div class="grid grid-cols-7 gap-1 text-xs text-center text-gray-500 mb-2">
          <div>Mon</div>
          <div>Tue</div>
          <div>Wed</div>
          <div>Thu</div>
          <div>Fri</div>
          <div>Sat</div>
          <div>Sun</div>
        </div>

        <div class="grid grid-cols-7 gap-1">
          <div
            v-for="day in calendarDays"
            :key="`${day.date}-${day.isCurrentMonth}`"
            class="h-8 flex items-center justify-center text-sm cursor-pointer rounded transition-colors"
            :class="getDayClasses(day)"
            @click="selectWeek(day.date)"
          >
            {{ day.day }}
          </div>
        </div>
      </div>

      <div class="mt-6 space-y-2">
        <p class="text-sm font-medium text-gray-700">Quick Select:</p>
        <div class="grid grid-cols-2 gap-2">
          <button
            @click="selectCurrentWeek"
            class="px-3 py-2 text-sm bg-blue-100 text-blue-700 rounded hover:bg-blue-200 transition-colors"
          >
            This Week
          </button>
          <button
            @click="selectPreviousWeek"
            class="px-3 py-2 text-sm bg-gray-100 text-gray-700 rounded hover:bg-gray-200 transition-colors"
          >
            Last Week
          </button>
          <button
            @click="selectNextWeek"
            class="px-3 py-2 text-sm bg-gray-100 text-gray-700 rounded hover:bg-gray-200 transition-colors"
          >
            Next Week
          </button>
          <button
            @click="selectThisMonth"
            class="px-3 py-2 text-sm bg-gray-100 text-gray-700 rounded hover:bg-gray-200 transition-colors"
          >
            This Month
          </button>
        </div>
      </div>

      <div class="flex justify-end space-x-3 mt-6">
        <button
          @click="closeModal"
          class="px-4 py-2 text-sm text-gray-700 bg-gray-200 rounded hover:bg-gray-300 transition-colors"
        >
          Cancel
        </button>
        <button
          @click="confirmSelection"
          class="px-4 py-2 text-sm text-white bg-blue-600 rounded hover:bg-blue-700 transition-colors"
        >
          Select Week
        </button>
      </div>
    </DialogContent>
  </Dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { X, ChevronLeft, ChevronRight } from 'lucide-vue-next'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { toLocalDateString } from '@/utils/dateUtils'

interface CalendarDay {
  date: Date
  day: number
  isCurrentMonth: boolean
  isToday: boolean
  isSelected: boolean
  isInSelectedWeek: boolean
}

interface Props {
  isOpen: boolean
  initialWeekStart?: string
}

interface Emits {
  (e: 'close'): void
  (e: 'weekSelected', weekStart: string, weekEnd: string): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

const currentDate = ref(new Date())
const selectedWeekStart = ref<string>(props.initialWeekStart || getCurrentWeekStart())
const selectedWeekEnd = ref<string>(getWeekEnd(selectedWeekStart.value))

const currentMonthYear = computed(() => {
  return currentDate.value.toLocaleDateString('en-US', {
    month: 'long',
    year: 'numeric',
  })
})

const weekNumber = computed(() => {
  const date = new Date(selectedWeekStart.value)
  return getWeekNumber(date)
})

const year = computed(() => {
  return new Date(selectedWeekStart.value).getFullYear()
})

const calendarDays = computed((): CalendarDay[] => {
  const year = currentDate.value.getFullYear()
  const month = currentDate.value.getMonth()

  const firstDay = new Date(year, month, 1)
  const firstMonday = new Date(firstDay)
  firstMonday.setDate(firstDay.getDate() - ((firstDay.getDay() + 6) % 7))

  const days: CalendarDay[] = []
  const today = new Date()
  const selectedWeekStartDate = new Date(selectedWeekStart.value)

  for (let i = 0; i < 42; i++) {
    const date = new Date(firstMonday)
    date.setDate(firstMonday.getDate() + i)

    const weekStart = getWeekStartDate(date)
    const isInSelectedWeek = weekStart === selectedWeekStart.value

    days.push({
      date,
      day: date.getDate(),
      isCurrentMonth: date.getMonth() === month,
      isToday: isSameDay(date, today),
      isSelected: isSameDay(date, selectedWeekStartDate),
      isInSelectedWeek,
    })
  }

  return days
})

function getCurrentWeekStart(): string {
  const today = new Date()
  return getWeekStartDate(today)
}

function getWeekStartDate(date: Date): string {
  const monday = new Date(date)
  const dayOfWeek = date.getDay()
  const diff = dayOfWeek === 0 ? -6 : 1 - dayOfWeek
  monday.setDate(date.getDate() + diff)
  return toLocalDateString(monday)
}

function getWeekEnd(weekStart: string): string {
  const startDate = new Date(weekStart)
  const endDate = new Date(startDate)
  endDate.setDate(startDate.getDate() + 6)
  return toLocalDateString(endDate)
}

function getWeekNumber(date: Date): number {
  const firstDayOfYear = new Date(date.getFullYear(), 0, 1)
  const pastDaysOfYear = (date.getTime() - firstDayOfYear.getTime()) / 86400000
  return Math.ceil((pastDaysOfYear + firstDayOfYear.getDay() + 1) / 7)
}

function isSameDay(date1: Date, date2: Date): boolean {
  return date1.toDateString() === date2.toDateString()
}

function formatWeekRange(start: string, end: string): string {
  const startDate = new Date(start)
  const endDate = new Date(end)

  if (startDate.getMonth() === endDate.getMonth()) {
    return `${startDate.getDate()}-${endDate.getDate()} ${startDate.toLocaleDateString('en-US', { month: 'short', year: 'numeric' })}`
  } else {
    return `${startDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} - ${endDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`
  }
}

function getDayClasses(day: CalendarDay): string {
  const classes = []

  if (!day.isCurrentMonth) {
    classes.push('text-gray-300')
  }

  if (day.isToday) {
    classes.push('bg-blue-100 text-blue-600 font-semibold')
  }

  if (day.isInSelectedWeek) {
    classes.push('bg-blue-600 text-white')
  } else if (day.isCurrentMonth) {
    classes.push('text-gray-700 hover:bg-gray-100')
  }

  return classes.join(' ')
}

function selectWeek(date: Date) {
  const weekStart = getWeekStartDate(date)
  selectedWeekStart.value = weekStart
  selectedWeekEnd.value = getWeekEnd(weekStart)
}

function selectCurrentWeek() {
  selectedWeekStart.value = getCurrentWeekStart()
  selectedWeekEnd.value = getWeekEnd(selectedWeekStart.value)
}

function selectPreviousWeek() {
  const current = new Date(selectedWeekStart.value)
  current.setDate(current.getDate() - 7)
  selectedWeekStart.value = getWeekStartDate(current)
  selectedWeekEnd.value = getWeekEnd(selectedWeekStart.value)
}

function selectNextWeek() {
  const current = new Date(selectedWeekStart.value)
  current.setDate(current.getDate() + 7)
  selectedWeekStart.value = getWeekStartDate(current)
  selectedWeekEnd.value = getWeekEnd(selectedWeekStart.value)
}

function selectThisMonth() {
  const today = new Date()
  currentDate.value = new Date(today.getFullYear(), today.getMonth(), 1)
  selectCurrentWeek()
}

function previousMonth() {
  currentDate.value = new Date(currentDate.value.getFullYear(), currentDate.value.getMonth() - 1, 1)
}

function nextMonth() {
  currentDate.value = new Date(currentDate.value.getFullYear(), currentDate.value.getMonth() + 1, 1)
}

function confirmSelection() {
  emit('weekSelected', selectedWeekStart.value, selectedWeekEnd.value)
  closeModal()
}

function closeModal() {
  emit('close')
}

watch(
  () => props.initialWeekStart,
  (newWeekStart) => {
    if (newWeekStart) {
      selectedWeekStart.value = newWeekStart
      selectedWeekEnd.value = getWeekEnd(newWeekStart)
    }
  },
)
</script>
