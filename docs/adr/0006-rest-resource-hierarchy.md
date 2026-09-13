# 0006 — Identifiers live in the URL path, bodies carry data only, one endpoint per operation

Identifiers live in the URL path; request bodies carry data only; one endpoint per operation.

## Rules

- Identifiers live in the URL path — never in the request body or query string. Bodies are pure payload, which is also what keeps them compatible with `If-Match` preconditions (ADR 0003) and the delta envelope (ADR 0004).
- One endpoint per operation. A view never branches on which path or body field is populated — overlapping URL patterns produce duplicate `operationId`s (`uploadJobFilesApi_2`), and a schema collision becomes an unusable method name in the generated frontend client (ADR 0021).
- When an endpoint's shape changes, the old URL returns `404` — no parallel old-and-new endpoints (ADR 0017).
- The reference shape is the job files resource: `/api/job/jobs/{job_id}/files/` (GET, POST), `/api/job/jobs/{job_id}/files/{file_id}/` (GET, PUT, DELETE) and `/api/job/jobs/{job_id}/files/{file_id}/thumbnail/` (GET) — six unique `operationId`s, every identifier in the path.
