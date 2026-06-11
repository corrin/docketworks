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

export async function getTimesheetJobs(page: Page) {
  const response = await page.request.get('/api/timesheets/jobs/', {
    headers: { Accept: 'application/json' },
  })
  const data = (await response.json()) as {
    jobs: Array<{
      job_number: number
      labour_rates: Array<{
        labour_subtype: string
        labour_subtype_name: string
        is_workshop: boolean
        charge_out_rate: number
      }>
    }>
  }
  return data.jobs
}
