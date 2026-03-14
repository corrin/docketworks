Project brief: Add minimal E2E test + auto-screenshots for Django + Vue app

Goal (MVP, ~4 hours)
Add a single end-to-end smoke test that:

Runs against the Vue frontend via ngrok (https://msm-workflow-front.ngrok-free.app).

Exercises one critical user flow end-to-end (login → core screen → core action).

Confirms the result is persisted by Django (either via UI round-trip or a small read-only API check).

Captures screenshots at key points into a fixed docs_screens/ folder for use in a manual.

Exposes a simple npm run test:e2e command as a pre-release check.

Assume:

Frontend: Vue (running behind ngrok).

Backend: Django (behind a separate ngrok URL).

Owner can start both servers and both ngrok tunnels manually before running the tests.

Phase 1 — Recon and assumptions

Locate the frontend repo (Vue project).

Confirm where package.json lives.

Confirm whether it’s Vite, Vue CLI, or something else.

Identify the main “core flow” to test by inspecting the code:

Look at the Vue router (e.g. src/router/index.ts or similar) to find:

Login route path.

Primary “job/workflow” route (e.g. /jobs, /workflow, /dashboard).

Find the components and selectors used there (labels, role names, data-testids, etc).

Confirm how the frontend talks to the backend:

Look for the API base URL (likely https://msm-workflow.ngrok-free.app) in an env file or config.

Don’t change that for now; just note it.

Do all of this by reading the repository – do not ask the user unless absolutely blocked.

Phase 2 — Install and configure Playwright in the frontend repo

From the frontend root (where package.json lives), add Playwright:

npm init playwright@latest

# or

# yarn create playwright

Choose:

Language: match repo (TS if possible).

Tests folder: default (tests is fine).

Browsers: keep defaults.

Install browsers: Yes.

Edit playwright.config.\*:

Set baseURL using an env var with a default to the ngrok frontend:

// playwright.config.ts
import { defineConfig } from '@playwright/test';

const baseURL =
process.env.MSM_FRONTEND_URL ??
'https://msm-workflow-front.ngrok-free.app';

export default defineConfig({
timeout: 60_000,
use: {
baseURL,
headless: true,
actionTimeout: 15_000,
},
});

This allows:

Default: uses ngrok URL (what the owner uses today).

Optionally: MSM_FRONTEND_URL=http://localhost:5173 later if needed.

Phase 3 — Create a single main flow test with screenshots

Objective: one test that covers login + core flow + screenshots.

Use Playwright’s codegen to bootstrap selectors:

npx playwright codegen https://msm-workflow-front.ngrok-free.app

In the browser window:

Log in as a valid test user (inspect the login form to get the selectors).

Navigate to the main “job/workflow” screen.

Perform a simple, safe action that clearly creates/updates a record (e.g. create a new job/work item with a unique name).

Save the generated code as tests/main-flow.spec.ts.

Refine the test:

Give the test a clear name.

Use robust selectors (getByRole, labels, data-testid) instead of brittle CSS if possible.

Add 3–4 screenshots into a docs_screens/ directory at meaningful points:

After login (dashboard).

Main list view.

After creating/viewing the new item.

Example structure (adjust selectors to match the real app):

import { test, expect } from '@playwright/test';

test('login and create core item (smoke + docs screenshots)', async ({ page }) => {
// Login
await page.goto('/login');
await page.getByLabel('Email').fill('test@example.com');
await page.getByLabel('Password').fill('password123');
await page.getByRole('button', { name: /log in/i }).click();

// Screenshot: dashboard after login
await page.waitForTimeout(1000);
await page.screenshot({
path: 'docs_screens/dashboard.png',
fullPage: true,
});

// Navigate to main list (e.g. jobs)
await page.getByRole('link', { name: /jobs/i }).click();

// Screenshot: jobs list
await page.waitForTimeout(1000);
await page.screenshot({
path: 'docs_screens/jobs_list.png',
fullPage: true,
});

// Create new item
const itemName = 'Playwright smoke item ' + Date.now();
await page.getByRole('button', { name: /new job|new item/i }).click();
await page.getByLabel(/name/i).fill(itemName);
await page.getByRole('button', { name: /save/i }).click();

// Screenshot: new item detail
await page.waitForTimeout(1000);
await page.screenshot({
path: 'docs_screens/job_detail.png',
fullPage: true,
});

// Force a fresh read from backend via UI:
// navigate back to list and assert our new item appears.
await page.getByRole('link', { name: /jobs/i }).click();
await expect(page.getByText(itemName)).toBeVisible();
});

Ensure docs_screens/ exists, and decide whether it should be committed to git or added to .gitignore. (Default: keep committed so docs can reference them; owner can adjust later.)

At this point you have:

One end-to-end smoke test.

UI-level verification that data round-trips via Django.

Screenshots ready for the manual.

Phase 4 — Add a simple backend verification (optional but low-cost)

If time allows, tighten the guarantee by checking Django via API.

4.1. Prefer existing API endpoint

Search the Django backend for an existing API endpoint for the core entity used above (e.g. Job):

Look in urls.py for api/ patterns.

Check DRF viewsets / views for something like /api/jobs/ or similar.

If a suitable read endpoint exists, use page.request in the Playwright test to check it after the UI flow:

const resp = await page.request.get(
'https://msm-workflow.ngrok-free.app/api/jobs/',
{ params: { search: itemName } } // adapt to actual filters
);
expect(resp.ok()).toBeTruthy();
const data = await resp.json();

// Adjust structure per API response
expect(data.results[0]).toMatchObject({
name: itemName,
// any other key fields to assert
});

4.2. If no suitable endpoint exists, add a narrow read-only one

Only do this if there is no simple existing endpoint.

In the Django backend:

Identify the main model used in the test (e.g. Job in some app).

Add a small, restricted API view that returns JSON for that model.

Example (adapt names and fields):

# views_test_api.py (or similar)

from django.http import JsonResponse, Http404
from django.contrib.admin.views.decorators import staff_member_required
from .models import Job

@staff_member_required
def job_detail_api(request, pk):
try:
job = Job.objects.get(pk=pk)
except Job.DoesNotExist:
raise Http404("Job not found")
return JsonResponse({
"id": job.id,
"name": job.name,
"status": job.status, # include only fields needed for automated checks
})

# urls.py

from .views_test_api import job_detail_api

urlpatterns += [
path("api/test/jobs/<int:pk>/", job_detail_api, name="job-detail-api"),
]

Guard it appropriately (e.g. staff-only, or only exposed in non-prod settings if desired).

In the Playwright test, capture the ID from the UI (if shown) or from the API list, then call the test endpoint and assert fields as above.

Only go this far if there’s time; the UI-only check is already a big win.

Phase 5 — Wire up a single npm script

In package.json in the frontend repo, add:

{
"scripts": {
"test:e2e": "playwright test tests/main-flow.spec.ts"
}
}

Now the owner can:

Start Django locally.

Start Vue frontend locally.

Start both ngrok tunnels so the frontend is at https://msm-workflow-front.ngrok-free.app and the backend at https://msm-workflow.ngrok-free.app.

Run:

npm run test:e2e

This should:

Run the single smoke test.

Fail if the core flow is broken.

Regenerate screenshots in docs_screens/.

Phase 6 — Minimal usage notes (for the owner)

Add a short docs/testing.md or a README section explaining:

Prereqs:

“Start Django, Vue, and ngrok tunnels for frontend and backend.”

Command:

npm run test:e2e

Screenshot locations:

docs_screens/dashboard.png, docs_screens/jobs_list.png, etc.

These are intended for inclusion in the manual.
