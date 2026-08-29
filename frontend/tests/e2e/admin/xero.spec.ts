/**
 * The Xero connection page: status, connect/reconnect, disconnect, manual sync.
 *
 * Read-only on purpose: the suite shares one live demo tenant, the global
 * preflight requires it CONNECTED before any spec runs, and clicking
 * Disconnect here would wipe the very tokens every later spec depends on;
 * Start Sync launches a real multi-minute sync. The mutation contracts are
 * proven in Django tests instead — apps/xero/tests/test_sync_dispatch.py
 * (202/409/401 dispatch), test_api.py (disconnect wipes tokens, office-only;
 * ping's 500-with-error_id), test_sync_stream.py (stream auth gate) — and
 * role gating likewise: the E2E account is office staff and superuser.
 */
import { expect, test } from '../fixtures/auth'
import { autoId } from '../helpers'

const SYNC_INFO_PATH = '/api/xero/sync-info/'

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
    await expect(autoId(page, 'XeroPage-connect')).toHaveCount(0)

    // The last-syncs table renders one row per synced entity from the live
    // sync-info payload; pay_items is pinned first by the backend contract.
    expect((await syncInfoResponse).status()).toBe(200)
    await expect(autoId(page, 'XeroPage-last-syncs-row-pay_items')).toBeVisible()
    await expect(autoId(page, 'XeroPage-last-syncs-row-contacts')).toBeVisible()
  })

  test('is reachable from the navbar via the Admin menu', async ({ authenticatedPage: page }) => {
    await page.goto('/kanban')
    // Owner ruling 2026-08-30: the entry lives under Admin (superuser menu),
    // even though the page's endpoints are office_auth.
    await autoId(page, 'AppNavbar-admin-menu').click()
    await autoId(page, 'AppNavbar-xero').click()
    await autoId(page, 'XeroPage-root').waitFor({ timeout: 30000 })
    await expect(page).toHaveURL(/\/admin\/xero$/)
  })
})
