import { createFileRoute } from '@tanstack/react-router'

import { FormEntriesPage } from '@/features/process'

export const Route = createFileRoute('/_authed/process-documents/forms/$category/$formId')({
  component: FormEntriesRoute,
})

function FormEntriesRoute() {
  const { category, formId } = Route.useParams()
  return <FormEntriesPage category={category} formId={formId} />
}
