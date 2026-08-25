import { createFileRoute } from '@tanstack/react-router'

import { ProcessFormsPage } from '@/features/process'

export const Route = createFileRoute('/_authed/process-documents/forms/$category/')({
  component: ProcessFormsRoute,
})

function ProcessFormsRoute() {
  const { category } = Route.useParams()
  return <ProcessFormsPage category={category} />
}
