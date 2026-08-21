import { createFileRoute, redirect } from '@tanstack/react-router'

/** The screen has no section-less state: land on the first section the schema
 *  defines (Company) rather than rendering an empty shell. */
export const Route = createFileRoute('/_authed/admin/company-defaults/')({
  beforeLoad: () => {
    throw redirect({ to: '/admin/company-defaults/$section', params: { section: 'company' } })
  },
})
