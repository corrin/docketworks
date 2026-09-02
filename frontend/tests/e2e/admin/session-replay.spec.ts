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

    // Playback: the events come back off disk and the player mounts on them.
    await page.goto('/admin/replays')
    await autoId(page, 'SessionReplayPage-recordings').waitFor({ timeout: 30000 })

    const row = page.locator('[data-automation-id="SessionReplayPage-recording-row"]').first()
    await expect(row).toBeVisible()

    const eventsLoaded = page.waitForResponse(
      (response) => response.url().includes('/events/') && response.status() === 200,
    )
    await row.click()
    const events = await eventsLoaded
    const played: unknown = (await events.json()).events
    expect(Array.isArray(played) && played.length > 0).toBe(true)

    // rrweb-player renders its own controller; its presence is the proof that
    // the events were playable, not merely returned.
    const player = autoId(page, 'SessionReplayPage-player')
    await expect(player.locator('.rr-controller')).toBeVisible({ timeout: 30000 })
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
