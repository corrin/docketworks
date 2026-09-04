/**
 * The boundary between the wire's opaque JSON and rrweb's event union.
 *
 * The server stores replay events verbatim and makes no claim about their
 * shape — giving them a structural type there would assert a version of
 * rrweb's format that nothing on the backend checks. The player does need
 * that shape, so it is checked here, once, rather than trusted: a recording
 * captured by an incompatible rrweb should fail visibly instead of leaving
 * the player showing a blank frame.
 */
import type { eventWithTime } from '@rrweb/types'

import type { RecordingEventsOut } from '@/api'

/**
 * Narrows from ``unknown`` rather than from the wire type: rrweb's
 * customEvent declares ``payload: unknown``, which is wider than JSON, so
 * eventWithTime is neither a subtype nor a supertype of what the wire
 * declares and no predicate between the two is expressible.
 */
function isPlayerEvent(event: unknown): event is eventWithTime {
  if (typeof event !== 'object' || event === null || Array.isArray(event)) return false
  // Opus: `data` is checked because rrweb's eventWithTime requires it and the
  // player reads it for every event type. Its absence is exactly the shape
  // drift this guard exists to catch, and without the check such an event
  // reaches the replayer and produces the blank frame the guard is meant to
  // prevent. Its CONTENTS are not checked: the shape varies per event type,
  // and asserting one here would be a claim about rrweb's wire format that
  // this file deliberately does not make.
  return (
    'type' in event &&
    typeof event.type === 'number' &&
    'timestamp' in event &&
    typeof event.timestamp === 'number' &&
    'data' in event
  )
}

export function toPlayerEvents(events: RecordingEventsOut['events']): eventWithTime[] {
  // A loop, not filter(): Array.filter constrains its predicate to a SUBTYPE
  // of the element, and these two types are unrelated. Narrowing in place
  // yields the intersection, which is what the player needs.
  const playable: eventWithTime[] = []
  for (const event of events) {
    if (!isPlayerEvent(event)) {
      throw new Error('Recording contains an event rrweb cannot replay')
    }
    playable.push(event)
  }
  return playable
}
