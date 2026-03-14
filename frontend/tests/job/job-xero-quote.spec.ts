import { test, expect } from '../fixtures/auth'
import { autoId } from '../fixtures/helpers'

const getJobIdFromUrl = (url: string): string => {
  const match = url.match(/\/jobs\/([a-f0-9-]+)/i)
  if (!match) {
    throw new Error(`Unable to parse job id from url: ${url}`)
  }
  return match[1]
}

const summarizeQuoteCostSet = async (page: import('@playwright/test').Page, jobId: string) => {
  const apiBaseUrl = process.env.VITE_API_BASE_URL
  const baseLabel = apiBaseUrl ? 'apiBase' : 'frontendBase'
  const baseUrl = apiBaseUrl ?? new URL(page.url()).origin
  const url = new URL(`/job/rest/jobs/${jobId}/cost_sets/`, baseUrl)
  url.searchParams.set('kind', 'quote')

  const response = await page.request.get(url.toString())
  const contentType = response.headers()['content-type'] || ''

  if (!response.ok()) {
    return `quote cost set fetch failed: ${response.status()} ${response.statusText()} ${baseLabel}`
  }

  const raw = await response.text()
  if (!raw.trim().startsWith('{') && !raw.trim().startsWith('[')) {
    const preview = raw.slice(0, 120).replace(/\s+/g, ' ').trim()
    return `quote cost set non-json response: ${preview || 'empty'} ${baseLabel} ${contentType}`
  }

  const data = JSON.parse(raw) as { cost_lines?: unknown[] }
  const lines = Array.isArray(data?.cost_lines) ? data.cost_lines : []
  const materialLines = lines.filter((line) => line?.kind === 'material')

  const hasStockId = (line: { ext_refs?: unknown }) => {
    if (!line?.ext_refs || typeof line.ext_refs !== 'object') return false
    const ext = line.ext_refs as Record<string, unknown>
    return Boolean(ext.stock_id)
  }

  const materialMissingStock = materialLines.filter((line) => !hasStockId(line))
  const missingDesc = lines.filter((line) => !line?.desc || String(line.desc).trim() === '')
  const zeroUnitRev = lines.filter((line) => Number(line?.unit_rev ?? 0) <= 0)

  return [
    `lines=${lines.length}`,
    `materialLines=${materialLines.length}`,
    `materialMissingStock=${materialMissingStock.length}`,
    `missingDesc=${missingDesc.length}`,
    `zeroUnitRev=${zeroUnitRev.length}`,
  ].join(' ')
}

const getQuoteUiSummary = async (page: import('@playwright/test').Page) => {
  const table = page.locator('.smart-costlines-table')
  const rows = table.locator('tbody tr')
  const rowCount = await rows.count()
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

  const summary = [
    `rows=${rowCount}`,
    `missingItem=${missingItemCount}`,
    `emptyDesc=${emptyDescCount}`,
    `zeroUnitRev=${zeroUnitRevCount}`,
  ].join(' ')
  return {
    summary,
    counts: {
      rowCount,
      missingItemCount,
      emptyDescCount,
      zeroUnitRevCount,
    },
  }
}

const normalizeQuoteUiLines = async (page: import('@playwright/test').Page) => {
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
        '[data-automation-id^="ItemSelect-option-"]:not([data-automation-id="ItemSelect-option-labour"])',
      )
      if (await nonLabourOption.count()) {
        await nonLabourOption.first().click()
      } else {
        await page.locator('[data-automation-id="ItemSelect-option-labour"]').first().click()
      }
      await page.waitForTimeout(800)
    }

    const descInput = row.locator('textarea')
    if (await descInput.count()) {
      const current = (await descInput.inputValue()).trim()
      if (!current) {
        await descInput.fill(`Auto line ${Date.now()}`)
        await descInput.blur()
        await page.waitForTimeout(800)
      }
    }

    const unitRevInput = row.locator('input[data-automation-id^="SmartCostLinesTable-unit-rev-"]')
    if (await unitRevInput.count()) {
      const raw = (await unitRevInput.inputValue()).trim().replace(/,/g, '')
      const value = raw ? Number(raw) : 0
      if (Number.isNaN(value) || value <= 0) {
        await unitRevInput.fill('1')
        await unitRevInput.blur()
        await page.waitForTimeout(800)
      }
    }
  }
}

test.describe('job xero quote', () => {
  test.setTimeout(120000)

  test('create quote in Xero from Quote tab', async ({
    authenticatedPage: page,
    sharedEditJobUrl,
  }) => {
    test.skip(true, 'to be refined')

    const jobId = getJobIdFromUrl(sharedEditJobUrl)

    await page.goto(sharedEditJobUrl)
    await page.waitForLoadState('networkidle')

    await autoId(page, 'JobViewTabs-quote').waitFor({ timeout: 10000 })
    await autoId(page, 'JobViewTabs-quote').click()

    const quoteSummary = await summarizeQuoteCostSet(page, jobId)
    const quoteUiBefore = await getQuoteUiSummary(page)
    console.log(`[Quote preflight] ${quoteSummary}`)
    console.log(`[Quote UI preflight] ${quoteUiBefore.summary}`)

    if (
      quoteUiBefore.counts.missingItemCount > 0 ||
      quoteUiBefore.counts.emptyDescCount > 0 ||
      quoteUiBefore.counts.zeroUnitRevCount > 0
    ) {
      await normalizeQuoteUiLines(page)
    }

    const quoteUiAfter = await getQuoteUiSummary(page)
    console.log(`[Quote UI preflight after] ${quoteUiAfter.summary}`)

    const createQuoteButton = page.getByRole('button', { name: 'Create Quote' })
    if ((await createQuoteButton.count()) > 0) {
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

      await page.pause()
      await page.getByRole('button', { name: 'Send Total Only' }).click()
      const response = await responsePromise
      if (!response.ok()) {
        const body = await response.text()
        throw new Error(
          `Xero quote create failed: ${response.status()} ${response.statusText()} ${body} | ${quoteSummary} | ${quoteUiAfter.summary}`,
        )
      }

      const responseBody = await response.json().catch(() => null)
      if (responseBody && responseBody.success === false) {
        const errorMessage =
          typeof responseBody.error === 'string' && responseBody.error.trim()
            ? responseBody.error
            : JSON.stringify(responseBody)
        throw new Error(`Xero quote create failed: ${errorMessage} | ${quoteSummary}`)
      }
    }

    await expect(page.getByRole('button', { name: /Open in Xero/ })).toBeVisible({
      timeout: 20000,
    })
  })
})
