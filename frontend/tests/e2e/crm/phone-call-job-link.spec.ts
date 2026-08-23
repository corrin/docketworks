import { spawnSync } from 'child_process'
import path from 'path'
import { fileURLToPath } from 'url'
import { z } from 'zod'

import { test, expect } from '../fixtures/auth'
import { autoId, createTestJob, expectStepUnder, getJobIdFromUrl } from '../helpers'

/**
 * Office staff link an imported phone-provider call to a job from the CRM
 * calls page, the link survives a reload, and the same call shows up on the
 * job's History tab. The no-prefetch assertion is the regression guard: one
 * <audio> per row with preload="metadata" made the browser download every
 * recording on page load.
 *
 * Two ids differ from v1 on purpose:
 * - `PhoneCallTable-job-select`, v1's native <select> of jobs, is retired: the
 *   job is chosen through the shared JobPicker, which opens from
 *   `PhoneCallTable-job-trigger` and lists `-job-option-{job_number}`.
 *   `PhoneCallTable-job-search` is unchanged — same id, now emitted by the
 *   picker rather than by a hand-rolled filter box.
 * - `PhoneCallTable-linked-job` is per row (`-linked-job-{callId}`): v1's
 *   shared id matched whichever linked row happened to sort first, so the
 *   assertion could pass on somebody else's call.
 * The seeded call also carries a real recording, so the <audio> assertion
 * below cannot pass vacuously on a page whose calls have no recordings.
 */

const specDir = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(specDir, '../../../..')
const managePy = path.join(repoRoot, 'manage.py')

const seededCallSchema = z.object({
  call_id: z.uuid(),
  recording_id: z.uuid(),
  job_number: z.number().int().positive(),
  download_url: z.string(),
})

type SeededCall = z.infer<typeof seededCallSchema>

/**
 * Seed one recorded, company-matched, job-less call against an E2E job.
 *
 * The phone provider is a pull-only portal, so an E2E environment can never
 * obtain a call the way production does; `e2e_seed_phone_call` fabricates one
 * and `e2e_cleanup` removes it by its `[TEST]` description.
 */
function seedPhoneCallForJob(jobId: string): SeededCall {
  // `uv run`, not bare `python`: the backend venv is uv-managed and nothing
  // guarantees an activated interpreter in the npm test environment.
  const result = spawnSync(
    'uv',
    ['run', 'python', managePy, 'e2e_seed_phone_call', '--job', jobId],
    {
      cwd: repoRoot,
      encoding: 'utf8',
      timeout: 120_000,
    },
  )

  if (result.error) {
    throw new Error(
      `Phone-call seed could not run: ${result.error.message}\n${result.stderr}\n${result.stdout}`,
    )
  }
  if (result.status !== 0) {
    throw new Error(
      `Phone-call seed failed with exit code ${result.status}:\n${result.stderr}\n${result.stdout}`,
    )
  }

  // The command's contract is a single JSON line, but the last non-empty line
  // is taken so stray startup logging can never break the parse.
  const finalOutputLine = result.stdout
    .split(/\r?\n/)
    .map((line) => line.trim())
    .findLast((line) => line.length > 0)
  if (!finalOutputLine) {
    throw new Error('Phone-call seed produced no JSON output')
  }

  let output: unknown
  try {
    output = JSON.parse(finalOutputLine)
  } catch (error) {
    throw new Error(`Phone-call seed final output was not JSON: ${finalOutputLine}`, {
      cause: error,
    })
  }
  return seededCallSchema.parse(output)
}

test('office staff links a CRM phone call to a job', async ({ authenticatedPage: page }) => {
  const jobUrl = await createTestJob(page, 'PhoneCallLink')
  const jobId = getJobIdFromUrl(jobUrl)
  const seeded = seedPhoneCallForJob(jobId)

  // Installed before the calls page is ever navigated to, or a fetch that
  // happens during that first load is invisible to the assertion below.
  const recordingFetches: string[] = []
  page.on('request', (request) => {
    if (/\/api\/crm\/phone-call-recordings\/[^/]+\/download\//.test(request.url())) {
      recordingFetches.push(request.url())
    }
  })

  await expectStepUnder('open CRM calls page', 3000, async () => {
    // Through the menu rather than page.goto: a route nothing navigates to is
    // a route users cannot reach, which is what route reachability asserts.
    await autoId(page, 'AppNavbar-crm-menu').click()
    await autoId(page, 'AppNavbar-calls').click()
    await expect(page).toHaveURL(/\/crm\/calls\/?$/)
    // The seeded call's call_datetime is now, so it is the first row of the
    // Recent queue. Measured against a development database holding ~45,000
    // real provider calls, that first page of 50 rows is 3.5 KB on the wire
    // (46.5 KB decompressed) — well under the 100 KB wire guard that
    // enableNetworkLogging applies to every /api/ response.
    await autoId(page, `PhoneCallTable-row-${seeded.call_id}`).waitFor()
  })

  const recording = autoId(page, `PhoneCallTable-recording-${seeded.call_id}`)
  await expect(recording).toBeAttached()
  await expect(recording).toHaveAttribute('preload', 'none')
  // The length is the one measured at archive time (the seed stores three
  // seconds of silence), stated before any fetch — a native control would
  // read 0:00 here.
  await expect(autoId(page, `PhoneCallTable-recording-${seeded.call_id}-time`)).toHaveText(
    '0:00 / 0:03',
  )
  expect(recordingFetches, 'no recording may be fetched until it is played').toEqual([])

  await expectStepUnder('open link job dialog', 2000, async () => {
    await autoId(page, `PhoneCallTable-link-job-${seeded.call_id}`).click()
    await expect(autoId(page, 'PhoneCallTable-link-dialog')).toBeVisible()
    await autoId(page, 'PhoneCallTable-job-trigger').click()
    await expect(autoId(page, 'PhoneCallTable-job-search')).toBeVisible()
  })

  await expectStepUnder('select job and save link', 2500, async () => {
    await autoId(page, 'PhoneCallTable-job-search').fill('PhoneCallLink')
    const option = autoId(page, `PhoneCallTable-job-option-${seeded.job_number}`)
    await expect(option).toBeVisible()
    await option.click()

    const linked = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === `/api/crm/phone-calls/${seeded.call_id}/job-link/` &&
        response.request().method() === 'POST' &&
        response.status() === 200,
    )
    await autoId(page, 'PhoneCallTable-save-job-link').click()
    await linked

    await expect(autoId(page, `PhoneCallTable-linked-job-${seeded.call_id}`)).toContainText(
      `Job #${seeded.job_number}`,
    )
  })

  await expectStepUnder('linked job persists after reload', 3500, async () => {
    await page.reload()
    await expect(autoId(page, `PhoneCallTable-linked-job-${seeded.call_id}`)).toContainText(
      `Job #${seeded.job_number}`,
    )
  })

  await expectStepUnder('linked call appears on job history', 7000, async () => {
    await page.goto(jobUrl)
    await autoId(page, 'JobViewTabs-history').click()
    await expect(autoId(page, `PhoneCallTable-linked-job-${seeded.call_id}`)).toContainText(
      `Job #${seeded.job_number}`,
    )
  })
})
