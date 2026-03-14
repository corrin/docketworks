import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import type { VueChatMessage } from '@/constants/vue-chat-message'
import { debugLog } from '@/utils/debug'
import { z } from 'zod'

type JobQuoteChat = z.infer<typeof schemas.JobQuoteChat>
type JobQuoteChatCreateRequest = z.infer<typeof schemas.JobQuoteChatCreateRequest>
type JobQuoteChatUpdate = z.infer<typeof schemas.JobQuoteChatUpdate>
type JobQuoteChatInteractionSuccessResponse = z.infer<
  typeof schemas.JobQuoteChatInteractionSuccessResponse
>
type JobQuoteChatHistoryResponse = z.infer<typeof schemas.JobQuoteChatHistoryResponse>
type JobQuoteChatInteractionRequest = z.infer<typeof schemas.JobQuoteChatInteractionRequest>

export class QuoteChatService {
  private static instance: QuoteChatService

  static getInstance(): QuoteChatService {
    if (!this.instance) {
      this.instance = new QuoteChatService()
    }
    return this.instance
  }

  async getChatHistory(jobId: string): Promise<JobQuoteChatHistoryResponse> {
    try {
      return await api.job_api_jobs_quote_chat_retrieve({ params: { job_id: jobId } })
    } catch (error) {
      debugLog('Failed to load chat history:', error)
      throw error
    }
  }

  async saveMessage(
    jobId: string,
    message: JobQuoteChatCreateRequest,
  ): Promise<JobQuoteChatInteractionSuccessResponse> {
    try {
      return await api.job_api_jobs_quote_chat_create(message, { params: { job_id: jobId } })
    } catch (error) {
      debugLog('Failed to save chat message:', error)
      throw error
    }
  }

  async updateMessage(
    jobId: string,
    messageId: string,
    updates: Partial<JobQuoteChat>,
  ): Promise<JobQuoteChatUpdate> {
    try {
      const payload = {
        content: updates.content,
        metadata: updates.metadata,
      }
      return await api.job_api_jobs_quote_chat_partial_update(payload, {
        params: { job_id: jobId, message_id: messageId },
      })
    } catch (error) {
      debugLog('Failed to update chat message:', error)
      throw error
    }
  }

  async clearChatHistory(jobId: string): Promise<void> {
    try {
      await api.quote_chat_delete_all(undefined, { params: { job_id: jobId } })
    } catch (error) {
      debugLog('Failed to clear chat history:', error)
      throw error
    }
  }

  convertToVueMessage(message: JobQuoteChat): VueChatMessage {
    return {
      _id: message.message_id || '',
      content: message.content || '',
      senderId: message.role === 'user' ? 'user-1' : 'assistant-1',
      username: message.role === 'user' ? 'You' : 'Quoting Assistant',
      timestamp: message.timestamp || new Date().toISOString(),
      system: false,
      metadata: (message.metadata as Record<string, unknown>) || undefined,
    }
  }

  convertFromVueMessage(
    vueMessage: VueChatMessage,
    role: 'user' | 'assistant',
  ): JobQuoteChatCreateRequest {
    return {
      message_id: vueMessage._id,
      role,
      content: vueMessage.content,
      metadata: vueMessage.metadata || {},
    }
  }

  async getAssistantResponse(
    jobId: string,
    message: string,
    mode: 'CALC' | 'PRICE' | 'TABLE' | 'AUTO' = 'AUTO',
  ): Promise<JobQuoteChat> {
    try {
      const request: JobQuoteChatInteractionRequest = { message, mode }
      const response = await api.job_api_jobs_quote_chat_interaction_create(request, {
        params: { job_id: jobId },
        timeout: 120000, // 2 minutes for AI processing
      })
      debugLog('Assistant response:', response)
      return response.data
    } catch (error) {
      debugLog('Failed to get assistant response:', error)
      throw error
    }
  }
}

export const quoteChatService = QuoteChatService.getInstance()
