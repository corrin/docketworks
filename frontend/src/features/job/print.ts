import { toast } from 'sonner'

import { apiErrorMessage, generateDeliveryDocketRest, jobJobsWorkshopPdfRetrieve } from '@/api'

async function openPdfInNewTab(fetchBlob: () => Promise<unknown>, label: string): Promise<void> {
  let data: unknown
  try {
    data = await fetchBlob()
  } catch (error) {
    toast.error(apiErrorMessage(error, `Failed to generate the ${label}.`))
    return
  }
  if (!(data instanceof Blob)) {
    toast.error(`The ${label} response was not a document.`)
    return
  }

  const url = URL.createObjectURL(data)
  const win = window.open(url, '_blank')
  if (!win) {
    // A blocked popup is the user's browser talking, not a defect — surface
    // it as a toast; a console.error here would fail every E2E spec.
    toast.error('Failed to open print window — check the popup blocker.')
    return
  }
  win.addEventListener('load', () => win.print())
}

export async function printWorkshopPdf(jobId: string): Promise<void> {
  await openPdfInNewTab(
    async () =>
      (
        await jobJobsWorkshopPdfRetrieve({
          path: { job_id: jobId },
          responseType: 'blob',
          throwOnError: true,
        })
      ).data,
    'workshop PDF',
  )
}

export async function printDeliveryDocket(jobId: string): Promise<void> {
  await openPdfInNewTab(
    async () =>
      (
        await generateDeliveryDocketRest({
          path: { job_id: jobId },
          responseType: 'blob',
          throwOnError: true,
        })
      ).data,
    'delivery docket',
  )
}
