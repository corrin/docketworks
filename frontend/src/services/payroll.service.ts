// src/services/payroll.service.ts

import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import type { z } from 'zod'
import axios, { getApiBaseUrl } from '@/plugins/axios'

export type CreatePayRunResponse = z.infer<typeof schemas.CreatePayRunResponse>
export type PayRunListItem = z.infer<typeof schemas.PayRunListItem>
export type PayRunListResponse = z.infer<typeof schemas.PayRunListResponse>
export type PayRunSyncResult = z.infer<typeof schemas.PayRunSyncResponse>

// Response from POST /api/payroll/post-staff-week/ (not in schema yet)
interface PostStaffWeekStartResponse {
  task_id: string
  stream_url: string
}

// SSE event types from the backend
export interface PostStaffWeekStartEvent {
  event: 'start'
  total: number
}

export interface PostStaffWeekProgressEvent {
  event: 'progress'
  staff_name: string
  current: number
  total: number
}

export interface PostStaffWeekCompleteEvent {
  event: 'complete'
  staff_id: string
  staff_name: string
  success: boolean
  work_hours?: string
  errors?: string[]
  skipped?: boolean
  reason?: string
  has_entries?: boolean
}

export interface PostStaffWeekDoneEvent {
  event: 'done'
  successful: number
  failed: number
}

export type PostStaffWeekSSEEvent =
  | PostStaffWeekStartEvent
  | PostStaffWeekProgressEvent
  | PostStaffWeekCompleteEvent
  | PostStaffWeekDoneEvent

export interface PostStaffWeekCallbacks {
  onStart?: (event: PostStaffWeekStartEvent) => void
  onProgress?: (event: PostStaffWeekProgressEvent) => void
  onComplete?: (event: PostStaffWeekCompleteEvent) => void
  onDone?: (event: PostStaffWeekDoneEvent) => void
  onError?: (error: Error) => void
}

/**
 * Create a new pay run for the specified week.
 *
 * @param weekStartDate - Monday of the week (YYYY-MM-DD format)
 * @returns Pay run details including ID and payment date
 * @throws Error if pay run already exists, invalid date, or Xero API error
 */
export async function createPayRun(weekStartDate: string): Promise<CreatePayRunResponse> {
  const response = await api.timesheets_api_payroll_pay_runs_create_create({
    week_start_date: weekStartDate,
  })
  return response as CreatePayRunResponse
}

/**
 * Post multiple staff members' weekly timesheets to Xero Payroll with SSE streaming.
 *
 * Uses the same pattern as Xero sync:
 * 1. POST to start the job → returns task_id and stream_url
 * 2. Connect via EventSource to receive progress events
 *
 * @param staffIds - Array of staff member UUIDs
 * @param weekStartDate - Monday of the week (YYYY-MM-DD format)
 * @param callbacks - Optional callbacks for SSE events (start, progress, complete, done, error)
 * @returns Promise that resolves when the stream completes
 */
export async function postStaffWeek(
  staffIds: string[],
  weekStartDate: string,
  callbacks?: PostStaffWeekCallbacks,
): Promise<PostStaffWeekDoneEvent> {
  // Step 1: Start the job
  const startResponse = await axios.post<PostStaffWeekStartResponse>(
    '/timesheets/api/payroll/post-staff-week/',
    {
      staff_ids: staffIds,
      week_start_date: weekStartDate,
    },
  )

  const { stream_url } = startResponse.data

  // Step 2: Connect to SSE stream using EventSource (matches Xero sync pattern)
  // Prefix with API base URL since frontend/backend may be on different origins
  // EventSource cannot send Authorization headers - pass token via query param for bearer auth
  let sseUrl = `${getApiBaseUrl()}${stream_url}`
  if (import.meta.env.VITE_AUTH_METHOD === 'bearer') {
    const token = localStorage.getItem('auth_token')
    if (token) {
      const separator = sseUrl.includes('?') ? '&' : '?'
      sseUrl += `${separator}token=${encodeURIComponent(token)}`
    }
  }

  return new Promise((resolve, reject) => {
    const eventSource = new EventSource(sseUrl, { withCredentials: true })
    let doneEvent: PostStaffWeekDoneEvent | null = null

    eventSource.onmessage = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data) as PostStaffWeekSSEEvent

        switch (data.event) {
          case 'start':
            callbacks?.onStart?.(data)
            break
          case 'progress':
            callbacks?.onProgress?.(data)
            break
          case 'complete':
            callbacks?.onComplete?.(data)
            break
          case 'done':
            doneEvent = data
            callbacks?.onDone?.(data)
            eventSource.close()
            resolve(data)
            break
        }
      } catch (parseError) {
        console.warn('Failed to parse SSE event:', event.data, parseError)
      }
    }

    eventSource.onerror = () => {
      eventSource.close()
      if (doneEvent) {
        // Already received done event, this is just the stream closing
        return
      }
      const error = new Error('Connection to payroll stream lost')
      callbacks?.onError?.(error)
      reject(error)
    }
  })
}

/**
 * Fetch all pay runs for the configured payroll calendar.
 * Returns pay runs sorted by period_end_date descending (newest first).
 *
 * Used to determine:
 * 1. Pay run status for a specific week (filter by period dates)
 * 2. Default week to show (latest Draft, or week after latest Posted)
 * 3. Whether current week can have a pay run posted (only weeks after latest Posted)
 *
 * @returns List of all pay runs
 */
export async function fetchAllPayRuns(): Promise<PayRunListResponse> {
  const response = await api.timesheets_api_payroll_pay_runs_retrieve()
  return response as PayRunListResponse
}

/**
 * Refresh cached pay runs from Xero and return synchronization stats.
 *
 * @returns Counts of fetched/created/updated pay runs from Xero.
 */
export async function refreshPayRuns(): Promise<PayRunSyncResult> {
  const response = await axios.post('/timesheets/api/payroll/pay-runs/refresh', {})
  return response.data as PayRunSyncResult
}
