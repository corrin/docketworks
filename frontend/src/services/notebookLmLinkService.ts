import { schemas } from '@/api/generated/api'
import { api } from '@/api/client'
import { debugLog } from '@/utils/debug'
import { z } from 'zod'

export type NotebookLmLink = z.infer<typeof schemas.NotebookLmLink>
export type NotebookLmLinkCreateUpdate = z.infer<typeof schemas.NotebookLmLinkRequest>

export class NotebookLmLinkService {
  private static instance: NotebookLmLinkService

  public static getInstance(): NotebookLmLinkService {
    if (!NotebookLmLinkService.instance) {
      NotebookLmLinkService.instance = new NotebookLmLinkService()
    }
    return NotebookLmLinkService.instance
  }

  private constructor() {}

  async getLinks(): Promise<NotebookLmLink[]> {
    try {
      return await api.workflow_notebook_lm_links_list()
    } catch (error) {
      debugLog('Failed to fetch NotebookLM links:', error)
      throw error
    }
  }

  /**
   * The enabled links the current user is allowed to see. Restriction
   * filtering happens server-side, so this is what the navbar renders.
   */
  async getMenuLinks(): Promise<NotebookLmLink[]> {
    try {
      return await api.workflow_notebook_lm_links_menu_list()
    } catch (error) {
      debugLog('Failed to fetch NotebookLM menu links:', error)
      throw error
    }
  }

  async createLink(linkData: NotebookLmLinkCreateUpdate): Promise<NotebookLmLink> {
    try {
      const created = await api.workflow_notebook_lm_links_create(linkData)
      return schemas.NotebookLmLink.parse(created)
    } catch (error) {
      debugLog('Failed to create NotebookLM link:', error)
      throw error
    }
  }

  async updateLink(
    id: number,
    linkData: Partial<NotebookLmLinkCreateUpdate>,
  ): Promise<NotebookLmLink> {
    try {
      const updated = await api.workflow_notebook_lm_links_partial_update(linkData, {
        params: { id },
      })
      return schemas.NotebookLmLink.parse(updated)
    } catch (error) {
      debugLog(`Failed to update NotebookLM link ${id}:`, error)
      throw error
    }
  }

  async deleteLink(id: number): Promise<void> {
    try {
      await api.workflow_notebook_lm_links_destroy(undefined, { params: { id } })
    } catch (error) {
      debugLog(`Failed to delete NotebookLM link ${id}:`, error)
      throw error
    }
  }

  async getLink(id: number): Promise<NotebookLmLink> {
    try {
      return await api.workflow_notebook_lm_links_retrieve({ params: { id } })
    } catch (error) {
      debugLog(`Failed to get NotebookLM link ${id}:`, error)
      throw error
    }
  }
}

export const notebookLmLinkService = NotebookLmLinkService.getInstance()
