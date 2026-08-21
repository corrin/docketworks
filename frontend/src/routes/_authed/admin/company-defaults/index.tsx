import { createFileRoute, redirect } from '@tanstack/react-router'

/** The screen has no section-less state, so bare /admin/company-defaults lands
 *  on a section. 'company' is pinned rather than read from the schema because
 *  beforeLoad runs before any fetch, and the section keys are a closed backend
 *  Literal (apps/core/settings_metadata.py SETTINGS_SECTIONS) whose first member
 *  cannot disappear without a migration of this route. */
export const Route = createFileRoute('/_authed/admin/company-defaults/')({
  beforeLoad: () => {
    throw redirect({ to: '/admin/company-defaults/$section', params: { section: 'company' } })
  },
})
