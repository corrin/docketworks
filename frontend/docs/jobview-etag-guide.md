Frontend integration guide: ETags and optimistic concurrency for Job operations

Context

- The backend now enforces optimistic concurrency on Job mutations using ETags.
- All Job GET endpoints return an ETag header based on Job.updated_at.
- Mutations (PUT, PATCH, DELETE, POST event, POST accept-quote) require clients to send If-Match with the latest ETag for that Job. Missing or mismatching ETags result in 428 or 412 responses.

Backend references

- ETag helpers and error mapping:
  - Base view helpers: BaseJobRestView.\_normalize_etag(), \_gen_job_etag(), \_get_if_match(), \_get_if_none_match(), \_precondition_required_response(), \_set_etag() (apps/job/views/job_rest_views.py:153)
  - 412 mapping in views: BaseJobRestView.handle_service_error() (apps/job/views/job_rest_views.py:92)
- GET endpoints that return ETag and support If-None-Match:
  - Job detail GET: JobDetailRestView.get() (apps/job/views/job_rest_views.py:305)
  - Job header GET: JobHeaderRestView.get() (apps/job/views/job_rest_views.py:707)
  - Job basic info GET: JobBasicInformationRestView.get() (apps/job/views/job_rest_views.py:1032)
- Mutations requiring If-Match:
  - Job update PUT: JobDetailRestView.put() (apps/job/views/job_rest_views.py:350)
  - Job update PATCH: JobDetailRestView.patch() (apps/job/views/job_rest_views.py:386)
  - Job delete DELETE: JobDetailRestView.delete() (apps/job/views/job_rest_views.py:435)
  - Job add event POST: JobEventRestView.post() (apps/job/views/job_rest_views.py:489)
  - Job accept quote POST: JobQuoteAcceptRestView.post() (apps/job/views/job_rest_views.py:598)
- Service layer optimistic checks and row locking:
  - Update with ETag and select_for_update: JobRestService.update_job() (apps/job/services/job_rest_service.py:301)
  - Delete with ETag and select_for_update: JobRestService.delete_job() (apps/job/services/job_rest_service.py:548)
  - Accept quote with ETag and select_for_update: JobRestService.accept_quote() (apps/job/services/job_rest_service.py:581)

Why this is required

- Prevents overwriting when two users edit the same job concurrently.
- Avoids duplicate actions from repeated requests.
- Prevents “data bleeding” by ensuring the mutation applies to the exact version retrieved by the client.

Client responsibilities

- Read ETag from response headers for each Job GET.
- Store ETag per Job ID. Never reuse across different jobs.
- Send If-Match with the stored ETag for all Job mutations:
  - PUT / PATCH / DELETE /jobs/{id}
  - POST /jobs/{id}/events
  - POST /jobs/{id}/accept-quote
- Optionally send If-None-Match on GET to get 304 and avoid transferring data when unchanged.
- Handle 412 Precondition Failed by reloading the job and retrying with the new ETag.

Minimal implementation strategy

- Keep a simple in-memory map keyed by job_id: etagByJob[jobId] = etagString
- On successful GET/PUT/PATCH/DELETE/POST event/accept-quote, update etagByJob[jobId] with the ETag header from the response.
- On 412, fetch the Job again (GET) to obtain the latest ETag and data, inform the user about concurrent changes, and allow retry.

Example with Axios interceptors (optional)

- Centralize ETag management via interceptors or a small wrapper.

```typescript
import axios from 'axios'

const etagByJob = new Map()
function getJobEtag(jobId) {
  return etagByJob.get(jobId) || null
}
function setJobEtag(jobId, etag) {
  if (etag) etagByJob.set(jobId, etag)
}

const api = axios.create({ baseURL: '/api' })

api.interceptors.response.use(
  (response) => {
    const url = response.config.url || ''
    const match = url.match(/\/jobs\/([0-9a-f-]{36})/i)
    if (match) {
      const jobId = match[1]
      const etag = response.headers['etag']
      setJobEtag(jobId, etag)
    }
    return response
  },
  async (error) => {
    const { response, config } = error
    if (response && (response.status === 412 || response.status === 428)) {
      const url = config.url || ''
      const match = url.match(/\/jobs\/([0-9a-f-]{36})/i)
      if (match) {
        const jobId = match[1]
        // Reload job to refresh ETag and data
        await api.get(`/jobs/${jobId}/`)
      }
      // Surface a user-friendly message
      return Promise.reject(
        new Error('Concurrent modification detected. Job reloaded. Please retry.'),
      )
    }
    return Promise.reject(error)
  },
)

// Usage examples:
async function updateJob(jobId, body) {
  const headers = {}
  const etag = getJobEtag(jobId)
  if (!etag) throw new Error('Missing ETag. Load job first.')
  headers['If-Match'] = etag
  return api.put(`/jobs/${jobId}/`, body, { headers })
}

async function addEvent(jobId, description) {
  const headers = {}
  const etag = getJobEtag(jobId)
  if (!etag) throw new Error('Missing ETag. Load job first.')
  headers['If-Match'] = etag
  return api.post(`/jobs/${jobId}/events/`, { description }, { headers })
}
```

UI handling recommendations

- When a 412 occurs, inform the user: “This job was updated by another user. We reloaded the latest data. Please re-apply your changes.”
- Consider a simple merge strategy for text fields: if local edits clash, show a diff and allow the user to re-apply.
- Disable action buttons while a previous mutation is in-flight to avoid double-submission.

Data isolation considerations

- Always store ETag keyed by Job ID. Never reuse an ETag between different jobs.
- When navigating away from a job, keep its ETag so users can return and still mutate safely. If you suspect staleness, do a quick GET to refresh the ETag.
- Events and accept-quote also depend on the job’s current ETag. Treat them as job mutations.

HTTP status reference

- 200 OK / 201 Created: success, ETag may be refreshed in response.
- 304 Not Modified: GET with If-None-Match matched, use cached data, no body.
- 400/403/404/409: business or validation errors.
- 412 Precondition Failed: If-Match did not match (concurrent update). Reload and retry.
- 428 Precondition Required: If-Match missing where required. Load and retry.

CORS note

- If the frontend is on a different origin and you use CORS, ensure the browser is allowed to send/receive the following headers:
  - Request headers: If-Match, If-None-Match
  - Response headers: ETag
- This typically requires adding these to Access-Control-Allow-Headers and Access-Control-Expose-Headers on the backend CORS configuration.

Testing checklist

- GET Job detail, capture ETag. Repeat GET with If-None-Match to confirm 304.
- Open Job in two tabs. Change from Tab A (PUT/PATCH). From Tab B, attempt mutation using old ETag and confirm 412. Tab B then GETs, receives new ETag, retries successfully.
- Rapidly press add event; duplicates are prevented and ETag is respected.
- Change client and ensure contact remains consistent or is cleared by backend protection if mismatched.

Change log

- ETag enforcement and conditional GET added in views and services; see references above.
- 412 PreconditionFailed mapped in Base view; see BaseJobRestView.handle_service_error().
- Additional defensive checks in service to prevent cross-client contact leakage post-update.

---

### IMPORTANT NOTE

- All endpoints that require e-tag handling are markend in the schema.yml file and also in the generated Zodios client (api.ts).

- You can find them by searching for the string "Concurrency is controlled in this endpoint (E-tag/If-Match)"
