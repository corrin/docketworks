import { createInstance, type i18n as I18n } from 'i18next'
import { initReactI18next } from 'react-i18next'

import admin from '@/locales/en/admin.json'
import crm from '@/locales/en/crm.json'
import job from '@/locales/en/job.json'
import kanban from '@/locales/en/kanban.json'
import processForms from '@/locales/en/process.json'
import purchasing from '@/locales/en/purchasing.json'
import reports from '@/locales/en/reports.json'
import shared from '@/locales/en/shared.json'
import shell from '@/locales/en/shell.json'
import timesheet from '@/locales/en/timesheet.json'
import proposedAdmin from '@/locales/proposed/admin.json'
import proposedCrm from '@/locales/proposed/crm.json'
import proposedJob from '@/locales/proposed/job.json'
import proposedKanban from '@/locales/proposed/kanban.json'
import proposedProcess from '@/locales/proposed/process.json'
import proposedPurchasing from '@/locales/proposed/purchasing.json'
import proposedReports from '@/locales/proposed/reports.json'
import proposedShared from '@/locales/proposed/shared.json'
import proposedShell from '@/locales/proposed/shell.json'
import proposedTimesheet from '@/locales/proposed/timesheet.json'

/**
 * Every word on a screen comes from these catalogues (ADR 0069), one file per
 * area under src/locales/en. English is the only language; the catalogue is
 * where the wording is read, discussed and changed.
 */
export const resources = {
  en: {
    admin,
    crm,
    job,
    kanban,
    process: processForms,
    purchasing,
    reports,
    shared,
    shell,
    timesheet,
  },
  // Opus: the wording under review (docs/adr/0069). Only the entries that
  // change; everything else falls back to en. Once the owner approves, these
  // values move into en and this overlay and its switch are deleted.
  proposed: {
    admin: proposedAdmin,
    crm: proposedCrm,
    job: proposedJob,
    kanban: proposedKanban,
    process: proposedProcess,
    purchasing: proposedPurchasing,
    reports: proposedReports,
    shared: proposedShared,
    shell: proposedShell,
    timesheet: proposedTimesheet,
  },
} as const

export type Wording = 'en' | 'proposed'

const WORDING_KEY = 'docketworks.wording'

/** `?wording=proposed` or `?wording=current` sets it; the browser remembers. */
function initialWording(): Wording {
  // Opus: node-environment unit tests load the catalogues with no browser.
  if (typeof window === 'undefined') return 'en'
  const asked = new URLSearchParams(window.location.search).get('wording')
  try {
    if (asked === 'proposed' || asked === 'current') {
      window.localStorage.setItem(WORDING_KEY, asked)
    }
    return window.localStorage.getItem(WORDING_KEY) === 'proposed' ? 'proposed' : 'en'
  } catch {
    // Opus: a browser that blocks site data throws on localStorage; the URL
    // still decides this page, and without it the current wording shows.
    return asked === 'proposed' ? 'proposed' : 'en'
  }
}

/** Flip the whole app between the current and the proposed wording. */
export function setWording(wording: Wording): void {
  try {
    window.localStorage.setItem(WORDING_KEY, wording === 'proposed' ? 'proposed' : 'current')
  } catch {
    // Opus: blocked site data: the flip still applies to this page.
  }
  void i18n.changeLanguage(wording)
}

const i18n: I18n = createInstance()

void i18n.use(initReactI18next).init({
  lng: initialWording(),
  fallbackLng: 'en',
  resources,
  ns: Object.keys(resources.en),
  defaultNS: false,
  // Resources are bundled, so init completes before the first render.
  initAsync: false,
  // React escapes rendered text already.
  interpolation: { escapeValue: false },
})

export { i18n }
