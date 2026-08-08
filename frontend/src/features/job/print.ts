import { generateDeliveryDocketRest, jobJobsWorkshopPdfRetrieve } from '@/api'
import { openBlobInNewTab } from './open-blob'

export async function printWorkshopPdf(jobId: string): Promise<void> {
  await openBlobInNewTab(
    async () =>
      (
        await jobJobsWorkshopPdfRetrieve({
          path: { job_id: jobId },
          responseType: 'blob',
          throwOnError: true,
        })
      ).data,
    'workshop PDF',
    { print: true },
  )
}

export async function printDeliveryDocket(jobId: string): Promise<void> {
  await openBlobInNewTab(
    async () =>
      (
        await generateDeliveryDocketRest({
          path: { job_id: jobId },
          responseType: 'blob',
          throwOnError: true,
        })
      ).data,
    'delivery docket',
    { print: true },
  )
}
