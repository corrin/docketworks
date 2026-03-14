<template>
  <Card class="w-full">
    <CardHeader class="pb-3">
      <div class="flex items-center justify-between">
        <h2 class="font-semibold">Comments</h2>
        <button
          @click="isAddOpen = !isAddOpen"
          class="inline-flex items-center px-3 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 transition-colors"
        >
          <ChevronDown
            :class="['w-4 h-4 mr-1.5 transition-transform', isAddOpen ? 'rotate-180' : '']"
          />
          Add Comment
        </button>
      </div>
    </CardHeader>
    <CardContent>
      <!-- Add Comment Form -->
      <Collapsible v-model:open="isAddOpen">
        <CollapsibleContent>
          <div class="mb-4 p-4 bg-gray-50 rounded-lg border">
            <textarea
              v-model="newComment"
              rows="3"
              class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              placeholder="Add a comment..."
              :disabled="isAdding"
            ></textarea>
            <div class="flex justify-end gap-2 mt-3">
              <Button variant="outline" size="sm" @click="cancelAdd" :disabled="isAdding">
                Cancel
              </Button>
              <Button size="sm" @click="addComment" :disabled="isAdding || !newComment.trim()">
                {{ isAdding ? 'Adding...' : 'Add Comment' }}
              </Button>
            </div>
          </div>
        </CollapsibleContent>
      </Collapsible>

      <!-- Loading State -->
      <div v-if="isLoading" class="text-center py-6">
        <div
          class="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600 mx-auto mb-2"
        ></div>
        <p class="text-sm text-gray-500">Loading comments...</p>
      </div>

      <!-- Comments List -->
      <div v-else-if="comments.length > 0" class="space-y-3">
        <div v-for="comment in comments" :key="comment.id" class="p-3 bg-white border rounded-lg">
          <p class="text-sm text-gray-900">{{ comment.description }}</p>
          <div class="flex items-center gap-2 mt-2 text-xs text-gray-500">
            <span class="font-medium">{{ comment.staff }}</span>
            <span>&bull;</span>
            <span>{{ formatTimestamp(comment.timestamp) }}</span>
          </div>
        </div>
      </div>

      <!-- Empty State -->
      <div v-else class="text-center py-6 text-sm text-gray-500">
        No comments yet. Add a comment to track notes about this purchase order.
      </div>
    </CardContent>
  </Card>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import { z } from 'zod'
import { toast } from 'vue-sonner'
import { Card, CardHeader, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { ChevronDown } from 'lucide-vue-next'

type PurchaseOrderEvent = z.infer<typeof schemas.PurchaseOrderEvent>

const props = defineProps<{
  poId: string
}>()

const comments = ref<PurchaseOrderEvent[]>([])
const isLoading = ref(false)
const isAdding = ref(false)
const isAddOpen = ref(false)
const newComment = ref('')

async function loadComments() {
  if (!props.poId) return

  isLoading.value = true
  try {
    const response = await api.listPurchaseOrderEvents({ params: { po_id: props.poId } })
    comments.value = response.events || []
  } catch (error) {
    toast.error('Failed to load comments')
    console.error('Failed to load comments:', error)
  } finally {
    isLoading.value = false
  }
}

async function addComment() {
  const text = newComment.value.trim()
  if (!text || !props.poId) return

  isAdding.value = true
  try {
    await api.createPurchaseOrderEvent({ description: text }, { params: { po_id: props.poId } })
    newComment.value = ''
    isAddOpen.value = false
    await loadComments()
    toast.success('Comment added')
  } catch (error) {
    toast.error('Failed to add comment')
    console.error('Failed to add comment:', error)
  } finally {
    isAdding.value = false
  }
}

function cancelAdd() {
  newComment.value = ''
  isAddOpen.value = false
}

function formatTimestamp(timestamp?: string) {
  if (!timestamp) return ''
  return new Date(timestamp).toLocaleString('en-NZ', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

onMounted(() => {
  loadComments()
})

watch(
  () => props.poId,
  () => {
    loadComments()
  },
)
</script>
