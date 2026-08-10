import { QueryClient } from '@tanstack/react-query'

import { registerConcurrencyInvalidator } from '@/lib/concurrency/interceptors'
import {
  getFullJobOptions,
  retrievePurchaseOrderQueryKey,
} from './generated/@tanstack/react-query.gen'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
})

// A 412/428 means another writer changed the resource; without this hook-up
// the interceptor's toast tells the user to retry against data the cache no
// longer reflects.
registerConcurrencyInvalidator('job', (jobId) =>
  queryClient.invalidateQueries({
    queryKey: getFullJobOptions({ path: { job_id: jobId } }).queryKey,
  }),
)

registerConcurrencyInvalidator('po', (poId) =>
  queryClient.invalidateQueries({
    queryKey: retrievePurchaseOrderQueryKey({ path: { po_id: poId } }),
  }),
)
