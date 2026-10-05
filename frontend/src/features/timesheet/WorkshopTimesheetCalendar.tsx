import type { EventDisplayInfo } from '@fullcalendar/react'
import FullCalendar from '@fullcalendar/react'
import interactionPlugin from '@fullcalendar/react/interaction'
// FullCalendar 7 ships no styles and no default theme: the skeleton is
// structural only, and a theme plugin plus its CSS is what draws the grid.
// Imported here rather than in main.css so the bundle only pays for them on
// the one route that mounts a calendar.
import '@fullcalendar/react/skeleton.css'
import classicThemePlugin from '@fullcalendar/react/themes/classic'
import '@fullcalendar/react/themes/classic/palette.css'
import '@fullcalendar/react/themes/classic/theme.css'
import timeGridPlugin from '@fullcalendar/react/timegrid'

import type { BreakOut, CalendarBoundsOut } from '@/api'

import { breakWords, type MyTimeCalendarEvent } from './myTime'

/** Calendar ids of break blocks, so a tap on one is not taken for an entry. */
const BREAK_EVENT_PREFIX = 'break-'

/** The block's own text: time, job, then where the entry stands, in words
    so the state does not rest on colour. */
function eventContent(marksById: Map<string, string[]>) {
  return function renderEventContent(arg: EventDisplayInfo) {
    if (arg.event.id.startsWith(BREAK_EVENT_PREFIX)) {
      return (
        <div
          className="overflow-hidden px-1 text-xs font-medium"
          data-break-id={arg.event.id.slice(BREAK_EVENT_PREFIX.length)}
        >
          {arg.event.title}
        </div>
      )
    }
    const marks = marksById.get(arg.event.id) ?? []
    return (
      <div className="overflow-hidden px-1 text-xs" data-event-id={arg.event.id}>
        <span className="font-medium">{arg.timeText}</span> {arg.event.title}
        <span className="ml-1 font-semibold" data-automation-id="WorkshopTimesheetCalendar-marks">
          {marks.join(' · ')}
        </span>
      </div>
    )
  }
}

interface WorkshopTimesheetCalendarProps {
  /** The day shown, YYYY-MM-DD; the page owns navigation, so the calendar's
      own toolbar stays off. */
  date: string
  /** The stretch of the day to open on, from the server ("HH:mm:ss"): the
      clocked span with an hour either side. Null while the day loads. */
  bounds: CalendarBoundsOut | null
  events: MyTimeCalendarEvent[]
  /** His breaks, drawn as their own blocks: part of the day's picture, not entries. */
  breaks: BreakOut[]
  onEventClick: (entryId: string) => void
  onBreakClick: (each: BreakOut) => void
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
  bounds,
  events,
  breaks,
  onEventClick,
  onBreakClick,
  onSlotClick,
}: WorkshopTimesheetCalendarProps) {
  const marksById = new Map(events.map((event) => [event.id, event.marks]))
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
        plugins={[timeGridPlugin, interactionPlugin, classicThemePlugin]}
        initialView="timeGridDay"
        initialDate={date}
        headerToolbar={false}
        allDaySlot={false}
        nowIndicator
        height="auto"
        slotDuration="00:30:00"
        {...(bounds === null ? {} : { slotMinTime: bounds.start, slotMaxTime: bounds.end })}
        // 24h faces, matching every other timesheet surface.
        slotHeaderFormat={{ hour: '2-digit', minute: '2-digit', hour12: false }}
        eventTimeFormat={{ hour: '2-digit', minute: '2-digit', hour12: false }}
        events={[
          ...events.map(({ id, title, start, end }) => ({ id, title, start, end })),
          ...breaks.map((each) => ({
            id: `${BREAK_EVENT_PREFIX}${each.id}`,
            title: breakWords(each),
            start: `${date}T${each.start}`,
            end: `${date}T${each.end}`,
            // Grey, and dashed for the one that comes off his hours: told
            // apart from an entry at a glance, and from each other in words.
            backgroundColor: '#e2e8f0',
            borderColor: '#64748b',
            textColor: '#0f172a',
          })),
        ]}
        eventClick={(info) => {
          const clicked = breaks.find((each) => `${BREAK_EVENT_PREFIX}${each.id}` === info.event.id)
          if (clicked === undefined) onEventClick(info.event.id)
          else onBreakClick(clicked)
        }}
        dateClick={(info) => {
          const [, time] = info.dateStr.split('T')
          if (time) onSlotClick(time.slice(0, 5))
        }}
        eventContent={eventContent(marksById)}
      />
    </div>
  )
}
