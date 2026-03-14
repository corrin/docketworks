import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import QuotingChatView from '../QuotingChatView.vue'
import type { VueChatMessage } from '@/services/quote-chat.service'

// Test data
const mockUserMessage: VueChatMessage = {
  _id: 'user-123',
  content: 'I need pricing for steel sheets',
  senderId: 'user-1',
  username: 'You',
  timestamp: new Date().toISOString(),
  system: false,
}

const mockAssistantMessage: VueChatMessage = {
  _id: 'assistant-456',
  content: 'I found several steel sheet options for you.',
  senderId: 'assistant-1',
  username: 'Quoting Assistant',
  timestamp: new Date().toISOString(),
  system: false,
  metadata: {
    tool_calls: [
      {
        name: 'search_products',
        arguments: { query: 'steel sheet', category: 'metal' },
        result_preview: 'Found 15 products matching your search criteria...',
      },
    ],
    model: 'gemini-1.5-pro',
  },
}

const mockAssistantMessageWithoutMetadata: VueChatMessage = {
  _id: 'assistant-789',
  content: 'Hello! How can I help you with your quote?',
  senderId: 'assistant-1',
  username: 'Quoting Assistant',
  timestamp: new Date().toISOString(),
  system: false,
}

// Use vi.hoisted() for variables referenced in vi.mock() factories
const { mockRouter, mockRoute, mockServiceInstance } = vi.hoisted(() => {
  const getChatHistoryMock = vi.fn()
  return {
    mockRouter: {
      push: vi.fn(),
    },
    mockRoute: {
      query: {
        jobId: 'test-job-id',
        jobName: 'Test Job',
        jobNumber: '2024-001',
        clientName: 'Test Client',
      },
    },
    mockServiceInstance: {
      getChatHistory: getChatHistoryMock,
      saveMessage: vi.fn().mockResolvedValue({ success: true }),
      getAssistantResponse: vi.fn().mockResolvedValue(null),
      clearChatHistory: vi.fn().mockResolvedValue({ success: true }),
      convertToVueMessage: vi.fn((msg: unknown) => msg),
      convertFromVueMessage: vi.fn((msg: unknown) => msg),
    },
  }
})

// Mock components and services
vi.mock('vue-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue-router')>()
  return {
    ...actual,
    useRoute: () => mockRoute,
    useRouter: () => mockRouter,
  }
})

vi.mock('@/services/quote-chat.service', () => ({
  QuoteChatService: {
    getInstance: () => mockServiceInstance,
  },
}))

vi.mock('@/utils/debug', () => ({
  debugLog: vi.fn(),
}))

vi.mock('vue-sonner', () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
    info: vi.fn(),
  },
}))

// Mock the API schemas to bypass validation
vi.mock('@/api/generated/api', () => ({
  schemas: {
    JobQuoteChat: {
      array: () => ({
        safeParse: (data: unknown) => ({ success: true, data }),
      }),
    },
  },
  endpoints: [],
}))

// Mock the API client to avoid initialization issues
vi.mock('@/api/client', () => ({
  api: {},
  getApi: () => ({}),
}))

// Helper to mount with messages loaded via the service mock
async function mountWithMessages(messages: VueChatMessage[]) {
  // Mock getChatHistory to return the messages
  mockServiceInstance.getChatHistory.mockResolvedValueOnce({
    success: true,
    data: { messages },
  })

  const wrapper = mount(QuotingChatView, {
    global: {
      stubs: {
        AppLayout: {
          template: '<div><slot /></div>',
        },
        McpToolDetails: {
          template: '<div data-testid="mcp-tool-details" class="mt-3">{{ metadata?.model }}</div>',
          props: ['metadata'],
        },
      },
    },
  })

  await flushPromises()
  return wrapper
}

describe('QuotingChatView MCP Integration', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Default: return empty messages
    mockServiceInstance.getChatHistory.mockResolvedValue({
      success: true,
      data: { messages: [] },
    })
  })

  describe('MCP tool details display', () => {
    it('shows tool details for assistant messages with metadata', async () => {
      const wrapper = await mountWithMessages([mockUserMessage, mockAssistantMessage])

      const toolDetails = wrapper.find('[data-testid="mcp-tool-details"]')
      expect(toolDetails.exists()).toBe(true)
    })

    it('does not show tool details for assistant messages without metadata', async () => {
      const wrapper = await mountWithMessages([
        mockUserMessage,
        mockAssistantMessageWithoutMetadata,
      ])

      const toolDetails = wrapper.find('[data-testid="mcp-tool-details"]')
      expect(toolDetails.exists()).toBe(false)
    })

    it('passes correct metadata to McpToolDetails component', async () => {
      const wrapper = await mountWithMessages([mockUserMessage, mockAssistantMessage])

      const toolDetails = wrapper.find('[data-testid="mcp-tool-details"]')
      expect(toolDetails.exists()).toBe(true)
      expect(toolDetails.text()).toContain('gemini-1.5-pro')
    })
  })

  describe('chat message layout with MCP integration', () => {
    it('handles mixed messages with and without metadata', async () => {
      const wrapper = await mountWithMessages([
        mockUserMessage,
        mockAssistantMessageWithoutMetadata,
        mockAssistantMessage,
      ])

      // Only the last message should have tool details
      const toolDetails = wrapper.findAll('[data-testid="mcp-tool-details"]')
      expect(toolDetails).toHaveLength(1)
    })
  })

  describe('error handling for corrupted metadata', () => {
    it('does not crash with null metadata', async () => {
      const messageWithNullMetadata: VueChatMessage = {
        ...mockAssistantMessage,
        metadata: null as unknown as Record<string, unknown>,
      }

      const wrapper = await mountWithMessages([mockUserMessage, messageWithNullMetadata])

      // Should not show tool details for null metadata
      const toolDetails = wrapper.find('[data-testid="mcp-tool-details"]')
      expect(toolDetails.exists()).toBe(false)
    })
  })
})
