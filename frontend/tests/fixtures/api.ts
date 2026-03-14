import type { Page } from '@playwright/test'

export async function getCompanyDefaults(page: Page) {
  const apiBaseUrl = process.env.VITE_API_BASE_URL
  const authToken = await page.evaluate(() => localStorage.getItem('auth_token'))
  const response = await page.request.get(`${apiBaseUrl}/api/company-defaults/`, {
    headers: {
      Authorization: `Bearer ${authToken}`,
      'ngrok-skip-browser-warning': 'true',
      Accept: 'application/json',
    },
  })
  return response.json()
}

export async function getStaffList(page: Page) {
  const apiBaseUrl = process.env.VITE_API_BASE_URL
  const authToken = await page.evaluate(() => localStorage.getItem('auth_token'))
  const response = await page.request.get(`${apiBaseUrl}/accounts/api/staff/`, {
    headers: {
      Authorization: `Bearer ${authToken}`,
      'ngrok-skip-browser-warning': 'true',
      Accept: 'application/json',
    },
  })
  return response.json()
}
