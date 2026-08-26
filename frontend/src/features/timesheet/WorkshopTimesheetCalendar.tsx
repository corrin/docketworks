import type { EventContentArg } from '@fullcalendar/core'
import interactionPlugin from '@fullcalendar/interaction'
import FullCalendar from '@fullcalendar/react'
import timeGridPlugin from '@fullcalendar/timegrid'

import type { MyTimeCalendarEvent } from './myTime'

function renderEventContent(arg: EventContentArg) {
  return (
    <div className="overflow-hidden px-1 text-xs" data-event-id={arg.event.id}>
      <span className="font-medium">{arg.timeText}</span> {arg.event.title}
    </div>
  )
}

interface WorkshopTimesheetCalendarProps {
  /** The day shown, YYYY-MM-DD; the page owns navigation, so the calendar's
      own toolbar stays off. */
  date: string
  events: MyTimeCalendarEvent[]
  onEventClick: (entryId: string) => void
  /** A click on an empty slot, as the slot's "HH:mm" start. */
  onSlotClick: (start: string) => void
}

/**
 * The one calendar: a single-day time grid drawing the staff member's own
 * entries. Blocks open the edit drawer; empty slots open the create drawer
 * with the clicked time as the start.
 *
 * Events render through eventContent so each block carries data-event-id —
 * the E2E spec's one DOM contract with this component.
 */
export function WorkshopTimesheetCalendar({
  date,
  events,
  onEventClick,
  onSlotClick,
}: WorkshopTimesheetCalendarProps) {
  return (
    <div
      className="rounded-lg border border-gray-200 bg-white p-2 shadow-sm"
      data-automation-id="WorkshopTimesheetCalendar"
    >
      <FullCalendar
        // Fable: Remounting per day rather than driving gotoDate through a
        // ref — a one-day time grid is cheap to rebuild, and the imperative
        // API is the only alternative FullCalendar offers for initialDate.
        key={date}
        plugins={[timeGridPlugin, interactionPlugin]}
        initialView="timeGridDay"
        initialDate={date}
        headerToolbar={false}
        allDaySlot={false}
        nowIndicator
        height="auto"
        slotDuration="00:30:00"
        // 24h faces, matching every other timesheet surface.
        slotLabelFormat={{ hour: '2-digit', minute: '2-digit', hour12: false }}
        eventTimeFormat={{ hour: '2-digit', minute: '2-digit', hour12: false }}
        events={events}
        eventClick={(info) => onEventClick(info.event.id)}
        dateClick={(info) => {
          const [, time] = info.dateStr.split('T')
          if (time) onSlotClick(time.slice(0, 5))
        }}
        eventContent={renderEventContent}
      />
    </div>
  )
}
