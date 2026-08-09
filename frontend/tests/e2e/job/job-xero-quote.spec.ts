import { spawnSync } from 'child_process'
import path from 'path'
import { fileURLToPath } from 'url'
import { z } from 'zod'
import type { Page } from '@playwright/test'

import { test, expect } from '../fixtures/auth'
import { autoId, createTestJob, getJobIdFromUrl, waitForAutosave } from '../helpers'

const specDir = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(specDir, '../../../..')
const managePy = path.join(repoRoot, 'manage.py')
const expectedTermsText = 'Terms of trade can be found'

const quotePdfInspectionSchema = z.object({
  quote_id: z.string().uuid(),
  remote_branding_theme_id: z.string().uuid().nullable(),
  configured_branding_theme_id: z.string().uuid().nullable(),
  page_count: z.number().int().positive(),
  contains_expected_text: z.boolean(),
})

type QuotePdfInspection = z.infer<typeof quotePdfInspectionSchema>

const createQuoteResponseSchema = z.object({
  success: z.boolean(),
  xero_id: z.string().uuid(),
  quote_id: z.string().uuid().nullable(),
  online_url: z.string().nullable(),
})

const inspectXeroQuotePdf = (quoteId: string): QuotePdfInspection => {
  // `uv run`, not bare `python`: the backend venv is uv-managed and nothing
  // guarantees an activated interpreter in the npm test environment.
  const result = spawnSync(
    'uv',
    [
      'run',
      'python',
      managePy,
      'inspect_xero_quote_pdf',
      quoteId,
      '--expected-text',
      expectedTermsText,
    ],
    {
      cwd: repoRoot,
      encoding: 'utf8',
      timeout: 120_000,
    },
  )

  if (result.error) {
    throw new Error(
      `Xero quote PDF inspection could not run: ${result.error.message}\n${result.stderr}\n${result.stdout}`,
    )
  }
  if (result.status !== 0) {
    throw new Error(
      `Xero quote PDF inspection failed with exit code ${result.status}:\n${result.stderr}\n${result.stdout}`,
    )
  }

  // The command's contract is a single JSON line, but the last non-empty
  // line is taken so stray startup logging can never break the parse.
  const finalOutputLine = result.stdout
    .split(/\r?\n/)
    .map((line) => line.trim())
    .findLast((line) => line.length > 0)
  if (!finalOutputLine) {
    throw new Error('Xero quote PDF inspection produced no JSON output')
  }

  let output: unknown
  try {
    output = JSON.parse(finalOutputLine)
  } catch (error) {
    throw new Error(`Xero quote PDF inspection final output was not JSON: ${finalOutputLine}`, {
      cause: error,
    })
  }
  return quotePdfInspectionSchema.parse(output)
}

const summarizeQuoteCostSet = async (page: Page, jobId: string) => {
  const baseUrl = new URL(page.url()).origin
  const url = new URL(`/api/job/jobs/${jobId}/cost_sets/quote/`, baseUrl)

  const response = await page.request.get(url.toString())
  const contentType = response.headers()['content-type'] || ''

  if (!response.ok()) {
    return `quote cost set fetch failed: ${response.status()} ${response.statusText()}`
  }

  const raw = await response.text()
  if (!raw.trim().startsWith('{') && !raw.trim().startsWith('[')) {
    const preview = raw.slice(0, 120).replace(/\s+/g, ' ').trim()
    return `quote cost set non-json response: ${preview || 'empty'} ${contentType}`
  }

  const costSetSchema = z.object({
    cost_lines: z.array(
      z.object({
        kind: z.string(),
        desc: z.string().nullable(),
        unit_rev: z.union([z.string(), z.number()]).nullable(),
        ext_refs: z.record(z.string(), z.unknown()),
      }),
    ),
  })
  const data = costSetSchema.parse(JSON.parse(raw))
  const lines = data.cost_lines
  const materialLines = lines.filter((line) => line.kind === 'material')
  const materialMissingStock = materialLines.filter((line) => !line.ext_refs['stock_id'])
  const missingDesc = lines.filter((line) => !line.desc || line.desc.trim() === '')
  const missingUnitRev = lines.filter((line) => line.unit_rev === null)
  const zeroUnitRev = lines.filter((line) => {
    if (line.unit_rev === null) return false
    const unitRev = Number(line.unit_rev)
    if (!Number.isFinite(unitRev)) return true
    return unitRev <= 0
  })

  return [
    `lines=${lines.length}`,
    `materialLines=${materialLines.length}`,
    `materialMissingStock=${materialMissingStock.length}`,
    `missingDesc=${missingDesc.length}`,
    `missingUnitRev=${missingUnitRev.length}`,
    `zeroUnitRev=${zeroUnitRev.length}`,
  ].join(' ')
}

const getQuoteUiSummary = async (page: Page) => {
  const table = page.locator('.smart-costlines-table')
  const rows = table.locator('tbody tr')
  const rowCount = await rows.count()
  // The last tbody row is always the trailing phantom; it never needs repair.
  const lastIndex = Math.max(0, rowCount - 1)

  let missingItemCount = 0
  let emptyDescCount = 0
  let zeroUnitRevCount = 0

  for (let i = 0; i < lastIndex; i += 1) {
    const row = rows.nth(i)
    if ((await row.getByRole('button', { name: 'Select Item' }).count()) > 0) {
      missingItemCount += 1
    }

    const descInput = row.locator('textarea')
    if (await descInput.count()) {
      const value = (await descInput.inputValue()).trim()
      if (!value) emptyDescCount += 1
    }

    const unitRevInput = row.locator('input[data-automation-id^="SmartCostLinesTable-unit-rev-"]')
    if (await unitRevInput.count()) {
      const raw = (await unitRevInput.inputValue()).trim().replace(/,/g, '')
      const value = raw ? Number(raw) : 0
      if (Number.isNaN(value) || value <= 0) zeroUnitRevCount += 1
    }
  }

  return {
    summary: [
      `rows=${rowCount}`,
      `missingItem=${missingItemCount}`,
      `emptyDesc=${emptyDescCount}`,
      `zeroUnitRev=${zeroUnitRevCount}`,
    ].join(' '),
    counts: { rowCount, missingItemCount, emptyDescCount, zeroUnitRevCount },
  }
}

const normalizeQuoteUiLines = async (page: Page) => {
  const table = page.locator('.smart-costlines-table')
  const rows = table.locator('tbody tr')
  const rowCount = await rows.count()
  const lastIndex = Math.max(0, rowCount - 1)

  for (let i = 0; i < lastIndex; i += 1) {
    const row = rows.nth(i)
    const selectItemButton = row.getByRole('button', { name: 'Select Item' })
    if (await selectItemButton.count()) {
      await selectItemButton.first().click()
      const optionList = page.locator('[data-automation-id^="ItemSelect-option-"]')
      await optionList.first().waitFor({ timeout: 5000 })
      const nonLabourOption = page.locator(
        '[data-automation-id^="ItemSelect-option-"]:not([data-automation-id^="ItemSelect-option-labour"])',
      )
      // Waiting on the PATCH landing, not a sleep: v1 slept 800ms to outlast
      // the 600ms debounce, which is exactly the flake this helper removes.
      const saved = waitForAutosave(page)
      if (await nonLabourOption.count()) {
        await nonLabourOption.first().click()
      } else {
        await page.locator('[data-automation-id^="ItemSelect-option-labour"]').first().click()
      }
      await saved
    }

    const descInput = row.locator('textarea')
    if (await descInput.count()) {
      const current = (await descInput.inputValue()).trim()
      if (!current) {
        const saved = waitForAutosave(page)
        await descInput.fill(`Auto line ${Date.now()}`)
        await descInput.blur()
        await saved
      }
    }

    const unitRevInput = row.locator('input[data-automation-id^="SmartCostLinesTable-unit-rev-"]')
    if (await unitRevInput.count()) {
      const raw = (await unitRevInput.inputValue()).trim().replace(/,/g, '')
      const value = raw ? Number(raw) : 0
      // isEnabled guard: a time line's rev input is disabled (priced from
      // rates); fill() on it would hang to the test timeout.
      if ((Number.isNaN(value) || value <= 0) && (await unitRevInput.isEnabled())) {
        const saved = waitForAutosave(page)
        await unitRevInput.fill('1')
        await unitRevInput.blur()
        await saved
      }
    }
  }
}

test.describe('job xero quote', () => {
  test.setTimeout(240000)

  test('create quote in Xero from Quote tab', async ({ authenticatedPage: page }) => {
    // A dedicated job, not sharedEditJobUrl: this spec repairs cost lines and
    // creates the job's one-and-only Xero quote, and the shared fixture is
    // read-only by contract. No in-spec Xero ping either — global setup
    // already fails the run closed on not-connected or readonly.
    const jobUrl = await createTestJob(page, 'Quote', {
      materials: '1000',
      time: '8',
      pricing: 'fixed_price',
    })
    const jobId = getJobIdFromUrl(jobUrl)

    await page.goto(jobUrl)
    await page.waitForLoadState('networkidle')

    await autoId(page, 'JobViewTabs-quote').waitFor({ timeout: 10000 })
    await autoId(page, 'JobViewTabs-quote').click()

    // Preflights are diagnostics for the failure message, never assertions:
    // a fresh job's quote lines are complete except the material line's
    // missing stock binding, which the normalize pass repairs below.
    const quoteSummary = await summarizeQuoteCostSet(page, jobId)
    await page.locator('.smart-costlines-table').waitFor({ timeout: 10000 })
    const quoteUiBefore = await getQuoteUiSummary(page)
    test
      .info()
      .annotations.push({ type: 'diagnostic', description: `Quote preflight ${quoteSummary}` })
    test.info().annotations.push({
      type: 'diagnostic',
      description: `Quote UI preflight ${quoteUiBefore.summary}`,
    })

    if (
      quoteUiBefore.counts.missingItemCount > 0 ||
      quoteUiBefore.counts.emptyDescCount > 0 ||
      quoteUiBefore.counts.zeroUnitRevCount > 0
    ) {
      await normalizeQuoteUiLines(page)
    }

    const quoteUiAfter = await getQuoteUiSummary(page)
    test.info().annotations.push({
      type: 'diagnostic',
      description: `Quote UI preflight after ${quoteUiAfter.summary}`,
    })

    const createQuoteButton = page.getByRole('button', { name: 'Create Quote' })
    await expect(
      createQuoteButton,
      'The fresh E2E job unexpectedly already has a Xero quote',
    ).toBeVisible()
    await createQuoteButton.click()
    await expect(page.getByText('Export Quote to Xero')).toBeVisible({ timeout: 10000 })

    const responsePromise = page.waitForResponse(
      (response) => {
        return (
          response.url().includes(`/api/xero/create_quote/${jobId}`) &&
          response.request().method() === 'POST'
        )
      },
      { timeout: 120000 },
    )

    await page.getByRole('button', { name: 'Send Total Only' }).click()
    const response = await responsePromise
    if (!response.ok()) {
      const body = await response.text()
      throw new Error(
        `Xero quote create failed: ${response.status()} ${response.statusText()} ${body} | ${quoteSummary} | ${quoteUiAfter.summary}`,
      )
    }

    const responseBody = createQuoteResponseSchema.parse(await response.json())
    if (!responseBody.success) {
      throw new Error(`Xero quote create reported failure | ${quoteSummary}`)
    }

    test.info().annotations.push({
      type: 'diagnostic',
      description: `Xero quote created quote ID: ${responseBody.xero_id}`,
    })

    await expect(page.getByRole('button', { name: /Open in Xero/ })).toBeVisible({
      timeout: 20000,
    })

    // The only proof Xero actually rendered the configured terms: download
    // the native PDF server-side and look for the marker text.
    const inspection = inspectXeroQuotePdf(responseBody.xero_id)
    expect(inspection.quote_id).toBe(responseBody.xero_id)

    const diagnostics = [
      `pages=${inspection.page_count}`,
      `remote_theme=${inspection.remote_branding_theme_id ?? 'null'}`,
      `configured_theme=${inspection.configured_branding_theme_id ?? 'null'}`,
    ].join(' ')
    // A matching theme ID alone can hide regressions where configured terms
    // are omitted from the API payload or the native Xero PDF.
    expect(
      inspection.contains_expected_text,
      `Xero-rendered quote PDF does not contain "${expectedTermsText}" (${diagnostics})`,
    ).toBe(true)
  })
})
