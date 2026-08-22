interface PageEnvelope {
  page: number
  total_pages: number
}

/**
 * `getNextPageParam` for any endpoint returning the
 * `{results, count, page, page_size, total_pages}` envelope: the next page
 * number, or undefined on the last page.
 */
export function nextPageParam(last: PageEnvelope): number | undefined {
  if (last.page >= last.total_pages) return undefined
  return last.page + 1
}
