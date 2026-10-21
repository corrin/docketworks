import { useTranslation } from 'react-i18next'

/** Text is pinned to exactly "Save failed" — an E2E spec asserts it verbatim. */
export function SaveFailedBadge() {
  const { t } = useTranslation('shared')
  return (
    <span className="inline-block rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
      {t('saveFailedBadge.label')}
    </span>
  )
}
