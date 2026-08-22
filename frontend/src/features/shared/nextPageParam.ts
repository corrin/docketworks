interface PageEnvelope {
  page: number
  total_pages: number
}

/**
 * `getNextPageParam` for every list endpoint that returns the shared
 * `paginate` envelope: the next page number, or undefined on the last page.
 */
export function nextPageParam(last: PageEnvelope): number | undefined {
  if (last.page >= last.total_pages) return undefined
  return last.page + 1
}
