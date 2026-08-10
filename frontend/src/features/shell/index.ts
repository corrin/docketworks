/**
 * App shell feature: the data every authenticated page needs before it renders,
 * and the chrome around the routed page (AppNavbar).
 */
import type { QueryClient } from '@tanstack/react-query'

import {
  companyDefaultsRetrieveOptions,
  dataVersionsRetrieveOptions,
  notebookLmLinksMenuListOptions,
} from '@/api'

export { AppNavbar } from './AppNavbar'

/** Query options for the CompanyDefaults singleton (GET /api/company-defaults/). */
export function companyDefaultsQueryOptions(): ReturnType<typeof companyDefaultsRetrieveOptions> {
  return {
    ...companyDefaultsRetrieveOptions(),
    staleTime: 5 * 60_000,
  }
}

/** Query options for the navbar NotebookLM menu (GET /api/ai/notebook-lm-links/menu/). */
export function notebookLmLinksQueryOptions(): ReturnType<typeof notebookLmLinksMenuListOptions> {
  return {
    ...notebookLmLinksMenuListOptions(),
    staleTime: 5 * 60_000,
  }
}

/** Query options for backend data versions (GET /api/data-versions/). */
export function dataVersionsQueryOptions(): ReturnType<typeof dataVersionsRetrieveOptions> {
  return {
    ...dataVersionsRetrieveOptions(),
    staleTime: 5 * 60_000,
  }
}

/**
 * Loads the shell data in its required order: company defaults, then the
 * NotebookLM menu, then data versions. The caller has already authenticated.
 * Failures propagate — a shell that cannot load its prerequisites must not
 * render pages that assume them.
 *
 * Only the initial data-versions fetch happens here. One consumer already
 * subscribes: useKanbanReconciliation puts a refetchInterval on
 * dataVersionsQueryOptions and diffs the `kanban` string against its cursor —
 * a second dataset wanting freshness adds an observer of the same query, not
 * a second poller.
 */
export async function ensureAppShellData(queryClient: QueryClient): Promise<void> {
  await queryClient.ensureQueryData(companyDefaultsQueryOptions())
  await queryClient.ensureQueryData(notebookLmLinksQueryOptions())
  await queryClient.ensureQueryData(dataVersionsQueryOptions())
}
