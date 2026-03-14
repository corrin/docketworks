<template>
  <div class="mcp-tool-details">
    <!-- Tool Summary Badge -->
    <div v-if="validMetadata && toolCallCount > 0" class="tool-summary mb-2">
      <Button
        variant="ghost"
        size="sm"
        @click="toggleDetails"
        class="h-8 px-2 text-xs hover:bg-gray-100"
        data-automation-id="McpToolDetails-toggle"
      >
        <div class="flex items-center space-x-2">
          <Badge variant="secondary" class="text-xs">
            {{ toolCallCount }} tool{{ toolCallCount > 1 ? 's' : '' }}
          </Badge>
          <span class="text-gray-600">used</span>
          <ChevronDown
            :class="['h-3 w-3 transition-transform', isDetailsExpanded ? 'rotate-180' : '']"
          />
        </div>
      </Button>
    </div>

    <!-- Error State -->
    <div v-else-if="hasMetadataError" class="error-state">
      <div class="bg-red-50 border border-red-200 rounded-lg p-3">
        <div class="flex items-center space-x-2">
          <AlertCircle class="h-4 w-4 text-red-500" />
          <p class="text-sm text-red-700">Tool details unavailable</p>
        </div>
        <p class="text-xs text-red-600 mt-1">{{ errorMessage }}</p>
      </div>
    </div>

    <!-- Tool Details Expandable Content -->
    <Collapsible v-if="validMetadata && toolCallCount > 0" v-model:open="isDetailsExpanded">
      <CollapsibleContent>
        <div class="tool-details-content border rounded-lg p-4 bg-gray-50 space-y-4">
          <!-- Loading State -->
          <div v-if="!detailsLoaded && isDetailsExpanded" class="loading-state">
            <div class="flex items-center justify-center p-6">
              <div class="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600"></div>
              <span class="ml-2 text-sm text-gray-600">Loading tool details...</span>
            </div>
          </div>

          <!-- Loaded Content -->
          <div v-else-if="detailsLoaded" class="loaded-content">
            <!-- Model Information -->
            <div v-if="validMetadata.model" class="model-info">
              <h3 class="text-sm font-medium text-gray-700 mb-2">Model Information</h3>
              <div class="bg-white rounded border p-3">
                <p class="text-xs text-gray-800">{{ validMetadata.model }}</p>
              </div>
            </div>

            <!-- Tool Definitions -->
            <div v-if="hasToolDefinitions" class="tool-definitions">
              <h3 class="text-sm font-medium text-gray-700 mb-2">Available Tools</h3>
              <div class="bg-white rounded border p-3">
                <div class="flex flex-wrap gap-2">
                  <Badge
                    v-for="(definition, index) in validMetadata.tool_definitions"
                    :key="index"
                    variant="outline"
                    class="text-xs"
                  >
                    {{ definition.name }}
                  </Badge>
                </div>
              </div>
            </div>

            <!-- Tool Calls -->
            <div
              v-if="validMetadata.tool_calls && validMetadata.tool_calls.length > 0"
              class="tool-calls"
            >
              <h3 class="text-sm font-medium text-gray-700 mb-2">Tool Calls Executed</h3>
              <div class="space-y-2">
                <!-- Virtual scrolling for large numbers of tool calls -->
                <div
                  v-if="toolCallCount > MAX_TOOL_CALLS_DIRECT_RENDER"
                  class="virtualized-tool-calls"
                  :style="{ maxHeight: '400px', overflowY: 'auto' }"
                >
                  <ToolCallDisplay
                    v-for="(toolCall, index) in visibleToolCalls"
                    :key="index"
                    :tool-call="toolCall"
                  />
                  <div v-if="hasMoreToolCalls" class="text-center mt-4">
                    <Button
                      variant="outline"
                      size="sm"
                      @click="loadMoreToolCalls"
                      :disabled="loadingMore"
                    >
                      {{ loadingMore ? 'Loading...' : `Load ${remainingToolCallCount} more` }}
                    </Button>
                  </div>
                </div>

                <!-- Direct render for small numbers -->
                <div v-else class="direct-render-tool-calls">
                  <ToolCallDisplay
                    v-for="(toolCall, index) in validMetadata.tool_calls"
                    :key="index"
                    :tool-call="toolCall"
                  />
                </div>
              </div>
            </div>

            <!-- System Prompt (Advanced) -->
            <div v-if="showAdvanced && validMetadata.system_prompt" class="system-prompt">
              <h3 class="text-sm font-medium text-gray-700 mb-2">System Prompt</h3>
              <div class="bg-white rounded border p-3">
                <p class="text-xs text-gray-800 whitespace-pre-wrap">{{ truncatedSystemPrompt }}</p>
                <Button
                  v-if="systemPromptTruncated"
                  variant="ghost"
                  size="sm"
                  @click="toggleFullSystemPrompt"
                  class="mt-2 h-6 text-xs text-blue-600 hover:text-blue-700"
                >
                  {{ showFullSystemPrompt ? 'Show Less' : 'Show Full Prompt' }}
                </Button>
              </div>
            </div>

            <!-- Actions -->
            <div class="flex justify-between items-center">
              <Button
                variant="ghost"
                size="sm"
                @click="copyAllMetadata"
                class="h-6 text-xs text-gray-500 hover:text-gray-700"
                data-automation-id="McpToolDetails-copy-all"
              >
                <Copy class="h-3 w-3 mr-1" />
                Copy All
              </Button>
              <Button
                variant="ghost"
                size="sm"
                @click="toggleAdvanced"
                class="h-6 text-xs text-gray-500 hover:text-gray-700"
                data-automation-id="McpToolDetails-toggle-advanced"
              >
                {{ showAdvanced ? 'Hide' : 'Show' }} Advanced Details
              </Button>
            </div>
          </div>
        </div>
      </CollapsibleContent>
    </Collapsible>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue'
import { ChevronDown, AlertCircle, Copy } from 'lucide-vue-next'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import ToolCallDisplay from './ToolCallDisplay.vue'
import {
  parseMetadata,
  getToolCallCount,
  type McpMetadata,
} from '@/schemas/mcp-tool-metadata.schema'

interface Props {
  /**
   * Raw metadata from the chat message
   */
  metadata?: Record<string, unknown>
  /**
   * Whether to show tool details expanded by default
   */
  defaultExpanded?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  defaultExpanded: false,
})

// Performance constants
const MAX_TOOL_CALLS_DIRECT_RENDER = 5
const TOOL_CALLS_LOAD_BATCH_SIZE = 3
const SYSTEM_PROMPT_TRUNCATE_LENGTH = 500

// Reactive state
const isDetailsExpanded = ref(props.defaultExpanded)
const showAdvanced = ref(false)
const detailsLoaded = ref(props.defaultExpanded)
const loadingMore = ref(false)
const visibleToolCallsCount = ref(MAX_TOOL_CALLS_DIRECT_RENDER)
const showFullSystemPrompt = ref(false)

// Cleanup timers
let loadingTimer: ReturnType<typeof setTimeout> | null = null

const toggleDetails = () => {
  isDetailsExpanded.value = !isDetailsExpanded.value
}

const toggleAdvanced = () => {
  showAdvanced.value = !showAdvanced.value
}

const toggleFullSystemPrompt = () => {
  showFullSystemPrompt.value = !showFullSystemPrompt.value
}

// Performance optimization: lazy load details when expanded
watch(isDetailsExpanded, async (newValue) => {
  if (newValue && !detailsLoaded.value) {
    // Add a small delay to simulate loading and improve perceived performance
    loadingTimer = setTimeout(() => {
      detailsLoaded.value = true
    }, 100)
  }
})

// Load more tool calls for virtualized rendering
const loadMoreToolCalls = async () => {
  if (loadingMore.value || !validMetadata.value?.tool_calls) return

  loadingMore.value = true

  // Simulate loading delay for better UX
  await new Promise((resolve) => setTimeout(resolve, 150))

  const newCount = Math.min(
    visibleToolCallsCount.value + TOOL_CALLS_LOAD_BATCH_SIZE,
    validMetadata.value.tool_calls.length,
  )

  visibleToolCallsCount.value = newCount
  loadingMore.value = false
}

// Cleanup on unmount
onUnmounted(() => {
  if (loadingTimer) {
    clearTimeout(loadingTimer)
  }
})

/**
 * Parse and validate the metadata
 */
const metadataValidation = computed(() => {
  if (!props.metadata) {
    return { success: false, error: 'No metadata provided' }
  }

  return parseMetadata(props.metadata)
})

/**
 * Validated metadata object
 */
const validMetadata = computed((): McpMetadata | null => {
  return metadataValidation.value.success ? metadataValidation.value.data || null : null
})

/**
 * Whether there's a metadata error
 */
const hasMetadataError = computed(() => {
  return !metadataValidation.value.success && props.metadata !== undefined
})

/**
 * Error message for display
 */
const errorMessage = computed(() => {
  return metadataValidation.value.error || 'Unknown error'
})

/**
 * Number of tool calls
 */
const toolCallCount = computed(() => {
  return getToolCallCount(props.metadata)
})

/**
 * Whether there are tool definitions to show
 */
const hasToolDefinitions = computed(() => {
  return (
    validMetadata.value &&
    validMetadata.value.tool_definitions &&
    validMetadata.value.tool_definitions.length > 0
  )
})

/**
 * Visible tool calls for virtualized rendering
 */
const visibleToolCalls = computed(() => {
  if (!validMetadata.value?.tool_calls) return []

  return validMetadata.value.tool_calls.slice(0, visibleToolCallsCount.value)
})

/**
 * Whether there are more tool calls to load
 */
const hasMoreToolCalls = computed(() => {
  if (!validMetadata.value?.tool_calls) return false

  return visibleToolCallsCount.value < validMetadata.value.tool_calls.length
})

/**
 * Number of remaining tool calls to load
 */
const remainingToolCallCount = computed(() => {
  if (!validMetadata.value?.tool_calls) return 0

  return validMetadata.value.tool_calls.length - visibleToolCallsCount.value
})

/**
 * Truncated system prompt for display
 */
const truncatedSystemPrompt = computed(() => {
  if (!validMetadata.value?.system_prompt) return ''

  const prompt = validMetadata.value.system_prompt

  if (showFullSystemPrompt.value || prompt.length <= SYSTEM_PROMPT_TRUNCATE_LENGTH) {
    return prompt
  }

  return prompt.substring(0, SYSTEM_PROMPT_TRUNCATE_LENGTH) + '...'
})

/**
 * Whether system prompt is truncated
 */
const systemPromptTruncated = computed(() => {
  if (!validMetadata.value?.system_prompt) return false

  return validMetadata.value.system_prompt.length > SYSTEM_PROMPT_TRUNCATE_LENGTH
})

/**
 * Copy all metadata to clipboard
 */
const copyAllMetadata = async () => {
  if (!validMetadata.value) return

  try {
    const cleanedMetadata = {
      ...validMetadata.value,
      // Remove empty arrays and undefined values for cleaner output
      tool_calls: validMetadata.value.tool_calls?.length
        ? validMetadata.value.tool_calls
        : undefined,
      tool_definitions: validMetadata.value.tool_definitions?.length
        ? validMetadata.value.tool_definitions
        : undefined,
      chat_history: validMetadata.value.chat_history?.length
        ? validMetadata.value.chat_history
        : undefined,
    }

    // Remove undefined values
    const filteredMetadata = Object.fromEntries(
      Object.entries(cleanedMetadata).filter(([, value]) => value !== undefined),
    )

    const jsonString = JSON.stringify(filteredMetadata, null, 2)
    await navigator.clipboard.writeText(jsonString)

    console.log('All metadata copied to clipboard')
  } catch (error) {
    console.error('Failed to copy metadata:', error)

    // Fallback for older browsers
    const textArea = document.createElement('textarea')
    textArea.value = JSON.stringify(validMetadata.value, null, 2)

    document.body.appendChild(textArea)
    textArea.select()
    document.execCommand('copy')
    document.body.removeChild(textArea)
  }
}
</script>

<style scoped>
.mcp-tool-details {
  @apply select-none;
}

.tool-details-content {
  animation: fadeIn 0.2s ease-in-out;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(-4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
