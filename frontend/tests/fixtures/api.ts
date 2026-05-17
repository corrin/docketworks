import type { Page } from '@playwright/test'

export async function getCompanyDefaults(page: Page) {
  const response = await page.request.get('/api/company-defaults/', {
    headers: {
      Accept: 'application/json',
    },
  })
  return response.json()
}

export async function getStaffList(page: Page) {
  const response = await page.request.get('/api/accounts/staff/', {
    headers: {
      Accept: 'application/json',
    },
  })
  return response.json()
}

export async function getTimesheetStaff(page: Page, date?: string) {
  const params = date ? `?date=${date}` : ''
  const response = await page.request.get(`/api/timesheets/staff/${params}`, {
    headers: { Accept: 'application/json' },
  })
  const data = (await response.json()) as { staff: Array<{ id: string; wageRate: number }> }
  return data.staff
}
