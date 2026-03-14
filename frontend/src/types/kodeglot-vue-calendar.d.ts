declare module '@kodeglot/vue-calendar' {
  import type { DefineComponent } from 'vue'

  export type CalendarEvent = {
    id: string
    title: string
    start: string | Date
    end: string | Date
    tailwindColor?: string
    width?: number
    left?: number
    metadata?: Record<string, unknown>
    [key: string]: unknown
  }

  export type CalendarStore = {
    events: CalendarEvent[]
    monthEvents: CalendarEvent[]
    currentDate: Date
    addEvent: (event: CalendarEvent) => void
    addEvents: (events: CalendarEvent[]) => void
    updateEvent: (event: CalendarEvent) => void
    deleteEvent: (id: string) => void
    getEventsForDate: (date: Date) => CalendarEvent[]
    getEventsForWeek: (startDate: Date) => CalendarEvent[]
  }

  export const CalendarView: DefineComponent<
    Record<string, unknown>,
    Record<string, unknown>,
    Record<string, unknown>
  >
  export function useCalendarStore(): CalendarStore

  export default CalendarView
}
