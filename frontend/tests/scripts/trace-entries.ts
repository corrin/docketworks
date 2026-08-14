/**
 * Shared Playwright trace-file parsing for history-reporter.ts and
 * extract-trace-timing.ts. v1 carried this logic twice, drifting slightly;
 * one implementation here so the two readers cannot disagree about what a
 * trace call is. Entries are validated field-by-field from unknown JSON —
 * trace files are an undocumented internal format, so a malformed line is
 * skipped rather than trusted via a blanket cast.
 */
import AdmZip from 'adm-zip'

export interface TraceEntry {
  type: string
  callId?: string
  startTime?: number
  endTime?: number
  title?: string
  method?: string
  class?: string
  params?: { selector?: string; url?: string }
  error?: { message: string }
}

export interface TraceCall {
  start?: TraceEntry
  end?: TraceEntry
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function asString(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined
}

function asNumber(value: unknown): number | undefined {
  return typeof value === 'number' ? value : undefined
}

export function toTraceEntry(value: unknown): TraceEntry | null {
  if (!isObject(value)) return null
  const type = asString(value.type)
  if (!type) return null

  const params = isObject(value.params)
    ? { selector: asString(value.params.selector), url: asString(value.params.url) }
    : undefined
  const message = isObject(value.error) ? asString(value.error.message) : undefined

  return {
    type,
    callId: asString(value.callId),
    startTime: asNumber(value.startTime),
    endTime: asNumber(value.endTime),
    title: asString(value.title),
    method: asString(value.method),
    class: asString(value.class),
    params,
    error: message === undefined ? undefined : { message },
  }
}

/**
 * Pair every before/after event by callId across all .trace files in the zip.
 * A .trace entry that fails to read is reported through onEntryError (or
 * silently skipped without one) so a single corrupt file cannot lose the
 * whole trace.
 */
export function collectTraceCalls(
  traceZipPath: string,
  onEntryError?: (entryName: string, error: unknown) => void,
): Map<string, TraceCall> {
  const zip = new AdmZip(traceZipPath)
  const callMap = new Map<string, TraceCall>()

  for (const entry of zip.getEntries()) {
    if (!entry.entryName.endsWith('.trace')) continue
    try {
      const lines = entry.getData().toString('utf8').split('\n').filter(Boolean)
      for (const line of lines) {
        let parsed: unknown
        try {
          parsed = JSON.parse(line)
        } catch {
          continue // skip invalid JSON lines
        }
        const event = toTraceEntry(parsed)
        if (!event || !event.callId) continue
        let call = callMap.get(event.callId)
        if (!call) {
          call = {}
          callMap.set(event.callId, call)
        }
        if (event.type === 'before') call.start = event
        else if (event.type === 'after') call.end = event
      }
    } catch (error) {
      if (onEntryError) onEntryError(entry.entryName, error)
    }
  }

  return callMap
}
