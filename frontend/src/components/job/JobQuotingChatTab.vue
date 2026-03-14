<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <div class="flex-shrink-0 bg-white border-b border-gray-200 px-4 py-3">
      <div class="flex items-center justify-between">
        <div>
          <h3 class="text-lg font-medium text-gray-900">Interactive Quote Chat</h3>
          <p class="text-sm text-gray-500">AI assistant for quoting help</p>
        </div>
        <button
          @click="clearChatHistory"
          class="p-2 text-gray-400 hover:text-gray-600 transition-colors"
          title="Reset chat"
        >
          <RotateCcw class="w-4 h-4" />
        </button>
      </div>
    </div>

    <!-- Chat Messages -->
    <div class="flex-1 overflow-y-auto bg-gray-50 rounded-lg p-4 mb-4">
      <div class="space-y-4">
        <div
          v-for="message in messages"
          :key="message._id"
          :class="['flex', message.senderId === currentUserId ? 'justify-end' : 'justify-start']"
        >
          <div
            :class="[
              'rounded-lg p-4 max-w-md shadow-sm',
              message.senderId === currentUserId
                ? 'bg-blue-600 text-white'
                : 'bg-white text-gray-800',
            ]"
          >
            <div class="whitespace-pre-wrap">{{ message.content }}</div>
            <div class="text-xs mt-1 opacity-70">
              {{ formatTime(message.timestamp) }}
            </div>

            <!-- Mode indicator for Assistant Messages -->
            <div v-if="message.senderId !== currentUserId && message.metadata?.mode" class="mt-2">
              <span
                class="inline-flex items-center px-1.5 py-0.5 text-xs bg-gray-100 text-gray-600 rounded"
              >
                Mode: {{ message.metadata.mode }}
              </span>
            </div>

            <!-- MCP Tool Details for Assistant Messages -->
            <div v-if="message.senderId !== currentUserId && message.metadata" class="mt-3">
              <McpToolDetails :metadata="message.metadata" />
            </div>
          </div>
        </div>
        <!-- Loading indicator for AI response -->
        <div v-if="isLoading" class="flex justify-start">
          <div class="rounded-lg p-4 max-w-md shadow-sm bg-white text-gray-800">
            <div class="flex items-center space-x-2">
              <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
              <div class="flex flex-col">
                <span>{{ getLoadingMessage(currentMode) }}</span>
                <span class="text-xs text-gray-500 mt-1">This may take up to 2 minutes...</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Input Area -->
    <div class="flex-shrink-0 space-y-2">
      <!-- Mode Selector -->
      <fieldset class="mb-2">
        <legend class="text-xs text-gray-600 mb-1">Mode</legend>
        <div role="radiogroup" class="inline-flex rounded border overflow-hidden">
          <label
            v-for="m in modes"
            :key="m"
            class="px-2 py-1 text-xs cursor-pointer select-none border-r last:border-r-0"
            :class="[
              currentMode === m
                ? 'bg-blue-600 text-white border-blue-600'
                : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50',
              isLoading ? 'opacity-50 cursor-not-allowed' : '',
            ]"
          >
            <input
              class="sr-only"
              type="radio"
              name="quote-mode"
              :value="m"
              v-model="currentMode"
              :disabled="isLoading"
            />
            {{ m }}
          </label>
        </div>
      </fieldset>
      <div class="flex space-x-2">
        <div class="flex-1 relative">
          <textarea
            v-model="currentInput"
            @keydown.enter.exact.prevent="handleSendMessage"
            @keydown.enter.shift.exact="addNewLine"
            placeholder="Describe what you need fabricated..."
            class="w-full p-3 pr-12 border border-gray-300 rounded-lg resize-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            rows="3"
            :disabled="isLoading"
          />
          <input
            ref="fileInput"
            type="file"
            accept=".pdf,.jpg,.jpeg,.png,.dwg,.dxf"
            @change="handleFileUpload"
            class="hidden"
            multiple
          />
          <button
            @click="triggerFileUpload"
            class="absolute bottom-3 right-3 p-1 text-gray-400 hover:text-gray-600 transition-colors"
            title="Upload files"
          >
            <Paperclip class="w-4 h-4" />
          </button>
        </div>
        <button
          @click="handleSendMessage"
          :disabled="!currentInput.trim() || isLoading"
          class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Send class="w-4 h-4" />
        </button>
      </div>
      <p class="text-xs text-gray-500">Press Enter to send, Shift+Enter for new line</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { debugLog } from '@/utils/debug'
import { ref, onMounted } from 'vue'
import { Send, Paperclip, RotateCcw } from 'lucide-vue-next'
import McpToolDetails from '@/components/chat/McpToolDetails.vue'
import { QuoteChatService } from '@/services/quote-chat.service'
import type { VueChatMessage } from '@/constants/vue-chat-message'
import { schemas } from '@/api/generated/api'
import { toast } from 'vue-sonner'

interface Props {
  jobId: string
  jobName?: string
  jobNumber?: string
  clientName?: string
}

const props = defineProps<Props>()

type Mode = 'AUTO' | 'CALC' | 'PRICE' | 'TABLE'
const modes: Mode[] = ['AUTO', 'CALC', 'PRICE', 'TABLE']
const currentMode = ref<Mode>('AUTO')

const currentUserId = 'user-1'
const currentInput = ref('')
const isLoading = ref(false)
const fileInput = ref<HTMLInputElement>()

const messages = ref<VueChatMessage[]>([])

const buildWelcomeMessage = (): VueChatMessage => ({
  _id: `welcome-${Date.now()}`,
  content: `Hi! I'll help you create a quote for ${props.jobName || 'this job'}.\n\nPlease describe what you need fabricated.\n\nExample: "3 stainless steel boxes, 700Į-700Į-400mm, welded seams"`,
  senderId: 'assistant-1',
  username: 'Quoting Assistant',
  timestamp: new Date().toISOString(),
  system: false,
})

const handleSendMessage = async () => {
  if (!currentInput.value.trim() || isLoading.value) return

  const messageContent = currentInput.value.trim()
  debugLog('messageContent:', messageContent)
  currentInput.value = ''
  isLoading.value = true

  try {
    const userMessage: VueChatMessage = {
      _id: `user-${Date.now()}`,
      content: messageContent,
      senderId: currentUserId,
      username: 'You',
      timestamp: new Date().toISOString(),
      system: false,
    }
    debugLog('userMessage:', userMessage)
    messages.value.push(userMessage)

    await saveMessage(userMessage, 'user')

    const backendAssistantMessage = await quoteChatService.getAssistantResponse(
      props.jobId,
      messageContent,
      currentMode.value,
    )

    const assistantMessage = quoteChatService.convertToVueMessage(backendAssistantMessage)
    messages.value.push(assistantMessage)
  } catch (error) {
    debugLog('Chat processing failed:', error)
    const lastMessage = messages.value[messages.value.length - 1]
    if (lastMessage && lastMessage.senderId === 'assistant-1') {
      lastMessage.content = 'Sorry, I had trouble processing that. Please try again.'
    }
  } finally {
    isLoading.value = false
  }
}

const addNewLine = () => {
  currentInput.value += '\n'
}

const formatTime = (timestamp: string): string => {
  try {
    const date = new Date(timestamp)
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: true,
    })
  } catch (error) {
    debugLog('Error formatting time:', error)
    return 'Invalid time'
  }
}

const getLoadingMessage = (mode: Mode): string => {
  const messages: Record<Mode, string> = {
    AUTO: 'AI is analyzing your request...',
    CALC: 'AI is calculating dimensions and material requirements...',
    PRICE: 'AI is looking up current pricing information...',
    TABLE: 'AI is generating your quote summary...',
  }
  return messages[mode] || 'AI is processing your request...'
}

const quoteChatService = QuoteChatService.getInstance()

const loadChatHistory = async () => {
  try {
    const response = await quoteChatService.getChatHistory(props.jobId)

    if (response.success) {
      const rawMessages = Array.isArray(response.data?.messages) ? response.data.messages : []

      if (rawMessages.length > 0) {
        const vueMessages: VueChatMessage[] = []
        for (const rawMessage of rawMessages) {
          const parsed = schemas.JobQuoteChat.safeParse(rawMessage)
          if (parsed.success) {
            vueMessages.push(quoteChatService.convertToVueMessage(parsed.data))
          }
        }
        messages.value = vueMessages.length > 0 ? vueMessages : [buildWelcomeMessage()]
      } else {
        messages.value = [buildWelcomeMessage()]
      }
    }
  } catch (error) {
    console.error('Failed to load chat history:', error)
    toast.error('Failed to load chat history', {
      description: 'Could not retrieve previous conversation. Starting fresh.',
    })
  }
}

const saveMessage = async (message: VueChatMessage, role: 'user' | 'assistant') => {
  try {
    const backendMessage = quoteChatService.convertFromVueMessage(message, role)
    debugLog('backendMessage:', backendMessage)
    await quoteChatService.saveMessage(props.jobId, backendMessage)
  } catch (error) {
    console.error('Failed to save chat message:', error)
    toast.error('Failed to save message', {
      description: 'Message was not saved to database',
    })
  }
}

const clearChatHistory = async () => {
  if (confirm('Are you sure you want to clear the entire chat history? This cannot be undone.')) {
    try {
      await quoteChatService.clearChatHistory(props.jobId)

      messages.value = [
        {
          _id: 'welcome-1',
          content: `Hi! I'll help you create a quote for ${props.jobName || 'this job'}.\n\nPlease describe what you need fabricated.\n\nExample: "3 stainless steel boxes, 700×700×400mm, welded seams"`,
          senderId: 'assistant-1',
          username: 'Quoting Assistant',
          timestamp: new Date().toISOString(),
          system: false,
        },
      ]

      toast.success('Chat history cleared', {
        description: 'All messages have been deleted',
      })
    } catch (error) {
      console.error('Failed to clear chat history:', error)
      toast.error('Failed to clear chat history', {
        description: 'Could not delete messages from database',
      })
    }
  }
}

const triggerFileUpload = () => {
  fileInput.value?.click()
}

const handleFileUpload = async (event: Event) => {
  const target = event.target as HTMLInputElement
  const files = target.files

  if (!files || files.length === 0) return

  debugLog(
    'Files selected:',
    Array.from(files).map((f) => f.name),
  )

  toast.info('File upload', {
    description: `Selected ${files.length} file(s). File upload will be implemented next.`,
    duration: 4000,
  })

  target.value = ''
}

onMounted(async () => {
  debugLog('JobQuotingChatTab mounted for job:', props.jobId)
  await loadChatHistory()
  debugLog('Chat history loaded')
})
</script>
