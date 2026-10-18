import type { resources } from '@/lib/i18n'

// A key missing from the catalogue fails `npm run type-check`.
declare module 'i18next' {
  interface CustomTypeOptions {
    defaultNS: false
    resources: (typeof resources)['en']
  }
}
