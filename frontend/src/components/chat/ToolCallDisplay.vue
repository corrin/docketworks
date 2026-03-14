<template>
  <div class="tool-call-display border rounded-lg p-4 mb-3 bg-gray-50">
    <div class="flex items-center justify-between mb-2">
      <div class="flex items-center space-x-2">
        <Badge variant="outline" class="text-xs">{{ toolCall.name }}</Badge>
        <span class="text-sm text-gray-600">Tool Call</span>
      </div>
      <div class="flex items-center space-x-1">
        <Button
          v-if="hasArguments || hasResult"
          variant="ghost"
          size="sm"
          @click="copyToolCallData"
          class="h-6 w-6 p-0"
          title="Copy tool call data"
          data-automation-id="ToolCallDisplay-copy"
        >
          <Copy class="h-3 w-3" />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          @click="toggleExpanded"
          class="h-6 w-6 p-0"
          data-automation-id="ToolCallDisplay-toggle"
        >
          <ChevronDown
            :class="['h-4 w-4 transition-transform', isExpanded ? 'rotate-180' : '']"
            data-automation-id="ToolCallDisplay-chevron"
          />
        </Button>
      </div>
    </div>

    <Collapsible v-model:open="isExpanded">
      <CollapsibleContent>
        <div class="space-y-3">
          <!-- Arguments Section -->
          <div v-if="hasArguments" class="space-y-2">
            <h4 class="text-sm font-medium text-gray-700">Arguments</h4>
            <div class="bg-white rounded border p-3">
              <pre class="text-xs text-gray-800 whitespace-pre-wrap">{{ formattedArguments }}</pre>
            </div>
          </div>

          <!-- Result Preview Section -->
          <div v-if="hasResult" class="space-y-2">
            <h4 class="text-sm font-medium text-gray-700">Result Preview</h4>
            <div class="bg-white rounded border p-3">
              <p class="text-xs text-gray-800 whitespace-pre-wrap">{{ sanitizedResult }}</p>
              <p v-if="isResultTruncated" class="text-xs text-gray-500 mt-2 italic">
                Result truncated to 200 characters
              </p>
            </div>
          </div>

          <!-- No data message -->
          <div v-if="!hasArguments && !hasResult" class="text-sm text-gray-500 italic">
            No additional details available for this tool call
          </div>
        </div>
      </CollapsibleContent>
    </Collapsible>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { ChevronDown, Copy } from 'lucide-vue-next'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import type { ToolCall } from '@/schemas/mcp-tool-metadata.schema'

interface Props {
  toolCall: ToolCall
}

const props = defineProps<Props>()
const isExpanded = ref(false)

const toggleExpanded = () => {
  isExpanded.value = !isExpanded.value
}

const hasArguments = computed(() => {
  return props.toolCall.arguments && Object.keys(props.toolCall.arguments).length > 0
})

const hasResult = computed(() => {
  return props.toolCall.result_preview && props.toolCall.result_preview.trim().length > 0
})

const formattedArguments = computed(() => {
  if (!hasArguments.value) return ''

  try {
    return JSON.stringify(props.toolCall.arguments, null, 2)
  } catch {
    return String(props.toolCall.arguments)
  }
})

const sanitizedResult = computed(() => {
  if (!hasResult.value) return ''

  // Basic XSS prevention - strip HTML tags and limit length
  const result = props.toolCall.result_preview
    .replace(/<[^>]*>/g, '') // Remove HTML tags
    .trim()

  return result
})

const isResultTruncated = computed(() => {
  return hasResult.value && props.toolCall.result_preview.length >= 200
})

/**
 * Copy tool call data to clipboard
 */
const copyToolCallData = async () => {
  try {
    const data = {
      name: props.toolCall.name,
      arguments: props.toolCall.arguments,
      result_preview: props.toolCall.result_preview,
    }

    const jsonString = JSON.stringify(data, null, 2)
    await navigator.clipboard.writeText(jsonString)

    // You could add a toast notification here if available
    console.log('Tool call data copied to clipboard')
  } catch (error) {
    console.error('Failed to copy tool call data:', error)

    // Fallback for older browsers
    const textArea = document.createElement('textarea')
    textArea.value = JSON.stringify(
      {
        name: props.toolCall.name,
        arguments: props.toolCall.arguments,
        result_preview: props.toolCall.result_preview,
      },
      null,
      2,
    )

    document.body.appendChild(textArea)
    textArea.select()
    document.execCommand('copy')
    document.body.removeChild(textArea)
  }
}
</script>
