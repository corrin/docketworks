# Detect new app version and force reload

Trello: [#223 New Release - detect changed version and force reload](https://trello.com/c/0HU63ZBD)

## Context

After a deploy, users with open tabs continue running the old JS against the new API. Breaking schema changes then surface as Zod parse errors until the user does a manual hard refresh. Because we install on LAN (one installation per client, not multi-tenant), the failure mode is almost always a workstation that was asleep or offline during the deploy window — the tab never knew a new build was shipped.

**User context**: roughly ten non-technical users per install, all on the same LAN, releases about once a fortnight. The reload event fires rarely, but when it does it needs to work first-time for all of them — they cannot be told to hit Ctrl-Shift-R, and with ten users talking to each other, a single stuck tab becomes everyone's afternoon.

Goal: the SPA notices it is outdated and hard-reloads itself, with cache invalidation, without user action. No toast fallback, no sentinel dev value — strict equality between the SHA the backend reports and the SHA the frontend was built with.

## Approach

1. Both backend and frontend read `git rev-parse HEAD` directly — backend at Django settings import time, frontend at `vite` build/dev-server start via `define`. No `BUILD_ID` env var, no fallback, no `"dev"` sentinel.
2. Expose the SHA via an unauthenticated endpoint `GET /api/build-id/`.
3. Frontend polls every 5 minutes and on `visibilitychange`. On mismatch, hard-reload via `window.location.replace(<url-with-?__v=sha>)` — new URL each deploy so nginx and the browser cache can't serve stale `index.html`.
4. Nginx serves `index.html` with `Cache-Control: no-store` so the reload actually picks up new code even if some browser or intermediate decided to hold onto the old HTML.

## Backend changes

**1. Compute `BUILD_ID` from git at import time** — `docketworks/settings.py`

Near the top of the file (after `BASE_DIR` is defined), add:

```python
import subprocess
BUILD_ID = subprocess.run(
    ["git", "rev-parse", "HEAD"],
    cwd=BASE_DIR,
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()
```

No `os.getenv`, no default. If the checkout is missing `.git`, Django fails to start — that's correct (we only ever run from a git checkout, and a deploy without a git state is not a valid deployment).

Add the build-id URL path string to `LOGIN_EXEMPT_URLS` (settings.py:239) so the endpoint works before login.

**2. Endpoint** — new view file (e.g. `apps/workflow/views/build_id_view.py`)

```python
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

@api_view(["GET"])
@permission_classes([AllowAny])
def build_id_view(request):
    response = Response({"build_id": settings.BUILD_ID})
    response["Cache-Control"] = "no-store"
    return response
```

**3. URL routing** — `apps/workflow/urls.py`

Add `path("build-id/", build_id_view, name="build_id")` near the existing workflow endpoints (e.g. next to the `enums/` route at line 42). The workflow URLs are already mounted at `/api/`, so the final path is `/api/build-id/`.

**4. Schema regeneration**

After adding the endpoint, regenerate the OpenAPI schema so the frontend can use the generated client (per `frontend/CLAUDE.md` rule 3: "Only use generated `api` client — never raw fetch/axios"): `./manage.py spectacular --file frontend/schema.yml` (or the repo's equivalent command — check `npm run update-schema` script).

## Frontend changes

**1. Inject build SHA at compile time** — `frontend/vite.config.ts`

In `defineConfig`:

```ts
import { execSync } from 'node:child_process'
const buildId = execSync('git rev-parse HEAD').toString().trim()

export default defineConfig({
  define: { __BUILD_ID__: JSON.stringify(buildId) },
  // ...existing config
})
```

If `git rev-parse HEAD` fails, the build fails. That's correct.

Add the ambient type in `frontend/env.d.ts`: `declare const __BUILD_ID__: string`.

**2. Version-check composable** — new file `frontend/src/composables/useVersionCheck.ts`

Pattern: singleton module, started once from `main.ts`. Follow the interval/cleanup shape of `frontend/src/composables/useJobAutoSync.ts:57`.

```ts
import { api } from '@/api/client'

async function checkBuild() {
  const { build_id } = await api.buildId()  // generated client method
  if (build_id === __BUILD_ID__) return
  const url = new URL(window.location.href)
  url.searchParams.set('__v', build_id)
  window.location.replace(url.toString())
}

export function startVersionCheck() {
  checkBuild()
  setInterval(checkBuild, 5 * 60 * 1000)
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') checkBuild()
  })
}
```

- Hard reload only. No toast, no session flag. If the reload somehow lands on the same stale bundle, nginx + the query-param change will force a fresh fetch next tick; the SHA baked into the new bundle will match.
- Use the generated zodios client for the call, same as every other API call in the app.

**3. Bootstrap** — `frontend/src/main.ts`

After the existing Pinia/ETag setup block (line 61), call `startVersionCheck()` from the new composable.

## Nginx changes

**`scripts/server/templates/nginx-instance.conf.template`** — add a single targeted block above the existing `location /` so `index.html` is not cached:

```nginx
location = /index.html {
    root /opt/docketworks/instances/__INSTANCE__/frontend/dist;
    add_header Cache-Control "no-store" always;
}

location / {
    root /opt/docketworks/instances/__INSTANCE__/frontend/dist;
    try_files $uri $uri/ /index.html;
}
```

`index.html` must never be cached — it is the single file every SPA route is served (see existing `try_files $uri $uri/ /index.html` on line 33) and the only pointer to the current build's hashed bundle. All other files (hashed `/assets/*`, `favicon.ico`, `logo.png`, `manifest.json`) continue to be served by the existing `location /` block under default nginx cache behaviour; no change needed there for this feature.

## Deploy script change (nginx re-render)

`scripts/server/deploy.sh` currently never touches nginx. Rendered instance configs are written once at instance creation by `scripts/server/instance.sh:432-438`, so template edits don't reach live servers on their own.

In the per-instance loop of `deploy.sh` (around line 156, alongside the frontend build and gunicorn restart), add a step that re-renders the nginx config from the template and reloads nginx. Re-use the same `sed` invocation already in `instance.sh`:

```bash
# Re-render nginx config from template (picks up template changes)
FQDN=$(grep -E '^FQDN=' "$instance_dir/.env" | cut -d= -f2)
CERT_DOMAIN=$(grep -E '^CERT_DOMAIN=' "$instance_dir/.env" | cut -d= -f2)
sed \
    -e "s|__INSTANCE__|$instance|g" \
    -e "s|__FQDN__|$FQDN|g" \
    -e "s|__CERT_DOMAIN__|$CERT_DOMAIN|g" \
    "$SCRIPT_DIR/templates/nginx-instance.conf.template" \
    > "/etc/nginx/sites-available/docketworks-$instance"
```

After the loop, a single `nginx -t && systemctl reload nginx` (not per-instance — one reload covers all changed configs).

Idempotent: if the template is unchanged, the rendered config bytes are identical and `systemctl reload nginx` is cheap. No `certbot`/cert handling needed here — `instance.sh` is the only place that provisions certs; we are only rewriting the existing file.

Confirm the `.env` variables (`FQDN`, `CERT_DOMAIN`) actually exist in each instance's `.env` before committing to this exact lookup — `instance.sh` handles them at creation but we need to verify they're still present.

## Files to modify

- `docketworks/settings.py` — compute `BUILD_ID` from git; add URL to `LOGIN_EXEMPT_URLS`
- `apps/workflow/views/build_id_view.py` — new file
- `apps/workflow/urls.py` — register route
- `frontend/vite.config.ts` — inject `__BUILD_ID__`
- `frontend/env.d.ts` — declare `__BUILD_ID__`
- `frontend/src/composables/useVersionCheck.ts` — new file
- `frontend/src/main.ts` — start the checker
- `scripts/server/templates/nginx-instance.conf.template` — cache-control split
- `scripts/server/deploy.sh` — re-render nginx config per instance + single `nginx -s reload`

After the backend endpoint lands, regenerate the frontend schema so the generated client exposes the new method.

## Verification

**Local smoke test:**

1. Start Django + frontend dev server from a clean commit. Both compute the same SHA.
2. `curl http://localhost:8000/api/build-id/` → `{"build_id": "<full sha>"}` with `Cache-Control: no-store`. Works without a token (in `LOGIN_EXEMPT_URLS`).
3. `git commit` a trivial change and restart the backend (`./manage.py runserver` auto-reloads). Do not rebuild the frontend.
4. Within ≤5 minutes (or immediately after tab-switch away and back), the tab hard-reloads and the URL picks up a `?__v=<new_sha>` param.
5. Because the frontend bundle wasn't rebuilt, the reload lands on the same stale SHA. This is the dev-time reload-loop scenario — acceptable noise in dev, it goes away the moment the frontend dev server is restarted.

**End-to-end on UAT:**

1. Deploy a no-op commit to UAT (backend restart + frontend rebuild + nginx reload).
2. Confirm `/api/build-id/` returns the new full SHA, matching `__BUILD_ID__` baked into the deployed frontend.
3. Confirm a tab left open during the deploy reloads itself within 5 minutes, lands on the new URL with `?__v=<sha>`, and then stops reloading (new bundle matches new SHA).
4. Verify response headers on `/index.html` include `Cache-Control: no-store`.

**Regression:**

- `npm run type-check` in `frontend/`.
- Existing tests under `apps/workflow/tests/` should still pass; the new endpoint adds no coupling.
