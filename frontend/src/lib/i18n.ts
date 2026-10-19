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
} as const

const i18n: I18n = createInstance()

void i18n.use(initReactI18next).init({
  lng: 'en',
  resources,
  ns: Object.keys(resources.en),
  defaultNS: false,
  // Resources are bundled, so init completes before the first render.
  initAsync: false,
  // React escapes rendered text already.
  interpolation: { escapeValue: false },
})

export { i18n }
