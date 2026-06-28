import { spawnSync } from 'child_process'
import path from 'path'
import { fileURLToPath } from 'url'
import { expect, test } from '../fixtures/auth'
import { autoId, createTestJob, expectStepUnder } from '../fixtures/helpers'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(__dirname, '../../..')
const managePy = path.join(repoRoot, 'manage.py')

function jobIdFromUrl(url: string): string {
  const match = url.match(/\/jobs\/([0-9a-f-]{36})/)
  if (!match) {
    throw new Error(`Could not extract job id from URL: ${url}`)
  }
  return match[1]
}

function seedPhoneCallForJob(jobId: string): string {
  const code = `
from apps.job.models import Job
from apps.crm.models import PhoneCallRecord
from django.utils import timezone
from uuid import uuid4

job = Job.objects.select_related("client").get(id="${jobId}")
now = timezone.now()
call = PhoneCallRecord.objects.create(
    provider_call_id=f"e2e:{uuid4()}",
    account_code="e2e",
    call_datetime=now,
    call_date=now.date(),
    call_time=now.time(),
    call_type="Inbound",
    status="Answered",
    description="[TEST] CRM phone call job link",
    origin="+6421555123",
    destination="+6496365131",
    duration_seconds=67,
    client=job.client,
    raw_json={
        "id": "e2e",
        "calldate": now.date().isoformat(),
        "calltime": now.time().isoformat(timespec="seconds"),
        "origin": "+6421555123",
        "destination": "+6496365131",
    },
)
print(call.id)
`
  const result = spawnSync('python', [managePy, 'shell', '-c', code], {
    cwd: repoRoot,
    encoding: 'utf8',
  })
  if (result.status !== 0) {
    throw new Error(`Failed to seed phone call:\n${result.stderr}\n${result.stdout}`)
  }
  const callId = result.stdout.trim().split(/\s+/).at(-1)
  if (!callId) {
    throw new Error(`Phone call seed did not print an id: ${result.stdout}`)
  }
  return callId
}

test('office staff links a CRM phone call to a job', async ({ authenticatedPage: page }) => {
  const jobUrl = await createTestJob(page, 'PhoneCallLink')
  const jobId = jobIdFromUrl(jobUrl)
  const callId = seedPhoneCallForJob(jobId)

  await expectStepUnder('open CRM calls page', 3000, async () => {
    await page.goto('/crm/calls')
    await page.waitForLoadState('networkidle')
  })

  await expectStepUnder('open link job dialog', 2000, async () => {
    await autoId(page, `PhoneCallTable-link-job-${callId}`).click()
    await autoId(page, 'PhoneCallTable-job-select').waitFor({ timeout: 10000 })
  })

  await expectStepUnder('select job and save link', 2500, async () => {
    await autoId(page, 'PhoneCallTable-job-search').fill('PhoneCallLink')
    await autoId(page, 'PhoneCallTable-job-select').selectOption(jobId)
    await autoId(page, 'PhoneCallTable-save-job-link').click()
    await expect(autoId(page, 'PhoneCallTable-linked-job')).toContainText('Job #', {
      timeout: 10000,
    })
  })

  await expectStepUnder('linked job persists after reload', 3500, async () => {
    await page.reload()
    await page.waitForLoadState('networkidle')
    await expect(autoId(page, 'PhoneCallTable-linked-job')).toContainText('Job #', {
      timeout: 10000,
    })
  })

  await expectStepUnder('linked call appears on job history', 7000, async () => {
    await page.goto(jobUrl)
    await page.waitForLoadState('networkidle')
    await autoId(page, 'JobViewTabs-history').click()
    await expect(autoId(page, 'PhoneCallTable-linked-job')).toContainText('Job #', {
      timeout: 10000,
    })
  })
})
