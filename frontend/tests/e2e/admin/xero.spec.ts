/**
 * The Xero connection page: status, connect/reconnect, disconnect, manual sync.
 *
 * Connection changes remain read-only: the suite shares one live demo tenant, the global
 * preflight requires it CONNECTED before any spec runs, and clicking
 * Disconnect here would wipe the very tokens every later spec depends on;
 * Start Sync launches a real multi-minute sync. The detail action below spends
 * a complete employee refresh and requires an explicit live-call budget. Other contracts are
 * proven in Django tests instead — apps/xero/tests/test_sync_dispatch.py
 * (202/409/401 dispatch), test_api.py (disconnect wipes tokens, office-only;
 * ping's 500-with-error_id), test_sync_stream.py (stream auth gate) — and
 * role gating likewise: the E2E account is office staff and superuser.
 */
import type { Locator, Page, Response } from '@playwright/test'

import { expect, test } from '../fixtures/auth'
import { autoId } from '../helpers'

const SYNC_INFO_PATH = '/api/xero/sync-info/'

/** Ask for a detail refresh once the page believes no sync is running. */
async function dispatchDetailRefresh(page: Page, refresh: Locator): Promise<Response> {
  await expect(refresh).toBeEnabled({ timeout: 210_000 })
  const dispatched = page.waitForResponse(
    (r) => new URL(r.url()).pathname === '/api/xero/sync/' && r.request().method() === 'POST',
  )
  await refresh.click()
  return dispatched
}

test.describe('Xero connection page', () => {
  test('shows the connected state with sync and disconnect available', async ({
    authenticatedPage: page,
  }) => {
    const syncInfoResponse = page.waitForResponse(
      (r) => new URL(r.url()).pathname === SYNC_INFO_PATH && r.request().method() === 'GET',
    )
    await page.goto('/admin/xero')
    await autoId(page, 'XeroPage-root').waitFor({ timeout: 30000 })

    // The preflight guaranteed a connected tenant, so the page must say so —
    // and must offer the connected-state actions, not the connect button.
    await expect(autoId(page, 'XeroPage-status')).toContainText('Connected to Xero')
    await expect(autoId(page, 'XeroPage-start-sync')).toBeVisible()
    await expect(autoId(page, 'XeroPage-disconnect')).toBeVisible()
    await expect(autoId(page, 'XeroPage-refresh-details')).toBeVisible()
    await expect(autoId(page, 'XeroPage-last-detail-refresh')).toBeVisible()
    await expect(autoId(page, 'XeroPage-connect')).toHaveCount(0)

    // The last-syncs table renders one row per synced entity from the live
    // sync-info payload; pay_items is pinned first by the backend contract.
    expect((await syncInfoResponse).status()).toBe(200)
    await expect(autoId(page, 'XeroPage-last-syncs-row-pay_items')).toBeVisible()
    await expect(autoId(page, 'XeroPage-last-syncs-row-contacts')).toBeVisible()
  })

  test('refreshes employee details with progress and a successful timestamp', async ({
    authenticatedPage: page,
  }) => {
    test.setTimeout(240_000)
    await page.goto('/admin/xero')
    const refresh = autoId(page, 'XeroPage-refresh-details')

    // Opus: one lock covers every Xero sync, and the scheduler holds it
    // whenever it is due — so 409 `already_running` is the server being right,
    // not a defect. The button's disabled state cannot close the gap either: it
    // comes from a polled query, so it can still read "idle" while the
    // scheduler is taking the lock. Waiting for a quiet window and dispatching
    // again is what this spec can honestly assert; its subject is the detail
    // refresh, not who won the lock.
    const startedAt = Date.now()
    let response = await dispatchDetailRefresh(page, refresh)
    while (response.status() === 409) {
      await expect(refresh).toBeDisabled()
      await expect(refresh).toBeEnabled({ timeout: 210_000 })
      response = await dispatchDetailRefresh(page, refresh)
    }
    const completed = page.waitForResponse(
      async (r) => {
        if (new URL(r.url()).pathname !== SYNC_INFO_PATH || r.status() !== 200) return false
        const info = await r.json()
        return (
          info.last_detail_refresh !== null &&
          Date.parse(info.last_detail_refresh) >= startedAt &&
          !info.sync_in_progress
        )
      },
      { timeout: 210_000 },
    )
    expect(response.status()).toBe(202)
    expect(new URL(response.url()).searchParams.get('detail_refresh')).toBe('true')
    await expect(refresh).toBeDisabled()
    await expect(autoId(page, 'XeroPage-progress')).toContainText('Completed sync of employees', {
      timeout: 210_000,
    })
    await completed
    await expect(autoId(page, 'XeroPage-last-detail-refresh')).not.toContainText('never')
    await expect(refresh).toBeEnabled()
  })

  test('is reachable from the navbar via the Admin menu', async ({ authenticatedPage: page }) => {
    await page.goto('/kanban')
    // Owner ruling 2026-08-30: the entry lives under Admin for navbar
    // simplicity, not access control — the endpoints stay office_auth.
    await autoId(page, 'AppNavbar-admin-menu').click()
    await autoId(page, 'AppNavbar-xero').click()
    await autoId(page, 'XeroPage-root').waitFor({ timeout: 30000 })
    await expect(page).toHaveURL(/\/admin\/xero$/)
  })
})
