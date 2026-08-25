import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/_authed/process-documents/forms/$category/$formId')({
  component: FormEntriesRouteStub,
})

// Task 12 replaces this with the real FormEntriesPage (title, entry form,
// entries table, history/links dialogs). The route exists now so
// ProcessFormsPage's row navigation and its per-row Fill button have a real
// destination to land on.
function FormEntriesRouteStub() {
  const { category, formId } = Route.useParams()
  return (
    <div className="p-6 text-sm text-gray-500" data-automation-id="FormEntriesPage-root">
      Form entries page for {category}/{formId} arrives in Task 12.
    </div>
  )
}
