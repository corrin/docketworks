import { test, expect } from '../fixtures/auth'
import { autoId } from '../helpers'

/**
 * Session replay is the one feature no single layer can prove. Capture runs in
 * the browser, the payload lands as a gzip file on the server's disk, and only
 * the events endpoint reads it back and hands it to the player — so a chunk
 * that never uploads, a checksum that never matches, or a player that never
 * mounts all look identical to every unit test on either side.
 *
 * Capture is disabled for E2E by default (it would push chunk uploads through
 * the same tunnel the run is already slow on). This spec is the exception: it
 * clears that opt-out for its own context, because recording is the thing
 * under test.
 */

const DISABLE_KEY = 'e2e:disable-session-replay'
const CHUNK_UPLOAD = /\/api\/session-replays\/recordings\/[^/]+\/chunks\/$/
const EVENTS_FETCH = /\/api\/session-replays\/recordings\/[^/]+\/events\/$/

// rrweb-player renders the replay inside a SANDBOXED iframe so the recorded
// page's scripts cannot execute in the admin panel — which is the behaviour we
// want, and Chromium logs a console error each time it enforces it. Allowed
// rather than fixed: suppressing it would mean un-sandboxing someone else's
// captured page inside our own.
test.use({
  expectedConsoleErrors: [
    /Blocked script execution in .* because the document's frame is sandboxed/,
  ],
  // A replay is one recorded DOM stream, and the wire guard's 100 KB cap
  // cannot be met by any windowing of it: measured against the development
  // database, 162 events gzip to 162 KB and 1,180 to 557 KB, and the largest
  // single stored chunk is 940,739 bytes ALREADY compressed — so one rrweb
  // full-snapshot event alone exceeds the cap and no page size helps.
  // Exempted here rather than in the guard so every other spec still fails if
  // a page fetches a replay; the assertion below is what holds this one.
  largeResponseAllowlist: [EVENTS_FETCH],
})

test.describe('session replay', () => {
  test('a recorded session reaches the admin player', async ({ authenticatedPage: page }) => {
    await page.evaluate((key) => window.localStorage.removeItem(key), DISABLE_KEY)

    // The recording opens on the authenticated layout, so a reload is what
    // starts capture with the opt-out cleared.
    const recordingCreated = page.waitForResponse(
      (response) =>
        response.url().endsWith('/api/session-replays/recordings/') &&
        response.request().method() === 'POST',
    )
    await page.goto('/kanban')
    const created = await recordingCreated
    expect(created.status()).toBe(201)

    // Generate events rrweb will capture, then wait for the flush that carries
    // them. The flush interval is 10s, so the wait must outlast it.
    await page.mouse.move(200, 200)
    await page.mouse.move(400, 350)
    await page.keyboard.press('Escape')
    const chunkUploaded = await page.waitForResponse(
      (response) => CHUNK_UPLOAD.test(response.url()) && response.request().method() === 'POST',
      { timeout: 30000 },
    )
    expect(chunkUploaded.status()).toBe(201)
    expect((await chunkUploaded.json()).event_count).toBeGreaterThan(0)

    // Installed before the replays page is ever navigated to, or a fetch during
    // that first load would be invisible to the assertion below.
    const eventFetches: string[] = []
    page.on('request', (request) => {
      if (EVENTS_FETCH.test(request.url())) eventFetches.push(request.url())
    })

    await page.goto('/admin/replays')
    await autoId(page, 'SessionReplayPage-recordings').waitFor({ timeout: 30000 })

    const row = page.locator('[data-automation-id="SessionReplayPage-recording-row"]').first()
    await expect(row).toBeVisible()

    // Selecting a recording shows its metadata and costs nothing. A replay is
    // hundreds of KB even gzipped, so browsing the list must not download one.
    await row.click()
    const play = autoId(page, 'SessionReplayPage-play')
    await expect(play).toBeVisible()
    expect(eventFetches, 'no replay may be fetched until it is loaded').toEqual([])

    // Playback: the events come back off disk and the player mounts on them.
    // URL and method only, never status (ADR 0025) — a status-filtered wait
    // could not match the 409 a missing payload returns, so a real failure
    // would surface as a timeout instead of its own message.
    const eventsLoaded = page.waitForResponse(
      (response) => EVENTS_FETCH.test(response.url()) && response.request().method() === 'GET',
    )
    await play.click()
    const events = await eventsLoaded
    expect(events.status(), await events.text()).toBe(200)
    const played: unknown = (await events.json()).events
    expect(Array.isArray(played) && played.length > 0).toBe(true)
    expect(eventFetches, 'loading a replay fetches it exactly once').toHaveLength(1)

    // rrweb-player renders its own controller; its presence is the proof that
    // the events were playable, not merely returned.
    const player = autoId(page, 'SessionReplayPage-player')
    await expect(player.locator('.rr-controller')).toBeVisible({ timeout: 30000 })
  })

  test('the recordings list pages rather than stopping at the first fifty', async ({
    authenticatedPage: page,
  }) => {
    await page.goto('/admin/replays')
    await autoId(page, 'SessionReplayPage-recordings').waitFor({ timeout: 30000 })

    // The seeded database holds far more recordings than one page, so the
    // count line proves the list knows about rows it has not loaded — the
    // defect being guarded is a list hard-pinned to page one with no way to
    // reach the rest.
    const count = autoId(page, 'SessionReplayPage-load-more-count')
    await expect(count).toBeVisible()
    const [, shown, total] = /Showing (\d+) of (\d+) recordings/.exec(
      (await count.textContent()) ?? '',
    ) ?? [null, '0', '0']
    expect(Number(total)).toBeGreaterThan(Number(shown))

    await page.getByRole('button', { name: 'Load more' }).click()
    await expect(count).not.toHaveText(`Showing ${shown} of ${total} recordings`)
  })

  test('the company toggle stops recording entirely', async ({ authenticatedPage: page }) => {
    await page.evaluate((key) => window.localStorage.removeItem(key), DISABLE_KEY)

    await page.goto('/admin/company-defaults/setup')
    const toggle = autoId(page, 'CompanyDefaultsPage-setup-field-session_replay_enabled')
    await toggle.waitFor({ timeout: 30000 })
    const wasEnabled = await toggle.isChecked()
    if (wasEnabled) {
      await toggle.click()
      await autoId(page, 'CompanyDefaultsPage-save-button').click()
      await expect(autoId(page, 'CompanyDefaultsPage-save-button')).toBeDisabled()
    }

    try {
      const refused = page.waitForResponse(
        (response) =>
          response.url().endsWith('/api/session-replays/recordings/') &&
          response.request().method() === 'POST',
        { timeout: 15000 },
      )
      await page.goto('/kanban')
      expect((await refused).status()).toBe(409)
    } finally {
      // Leave the instance recording: every later spec shares this database.
      if (wasEnabled) {
        await page.goto('/admin/company-defaults/setup')
        const restore = autoId(page, 'CompanyDefaultsPage-setup-field-session_replay_enabled')
        await restore.waitFor({ timeout: 30000 })
        await restore.click()
        await autoId(page, 'CompanyDefaultsPage-save-button').click()
      }
    }
  })
})
