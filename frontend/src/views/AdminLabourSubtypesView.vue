<template>
  <AppLayout>
    <div class="w-full h-full flex flex-col overflow-hidden">
      <div class="flex-1 overflow-y-auto p-0">
        <div class="max-w-5xl mx-auto py-8 px-2 md:px-8 h-full flex flex-col gap-8">
          <div class="flex items-center justify-between mb-2">
            <h1 class="text-3xl font-extrabold text-indigo-700 flex items-center gap-3">
              <Wrench class="w-8 h-8 text-indigo-400" />
              Labour Rates
            </h1>
            <Button
              variant="default"
              class="text-lg px-6 py-3"
              data-automation-id="AdminLabourSubtypesView-new"
              @click="openCreate"
            >
              New Subtype
            </Button>
          </div>
          <div v-if="loading" class="flex-1 flex items-center justify-center">
            <div class="flex items-center space-x-2 text-lg text-gray-600">
              <div class="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500"></div>
              <span>Labour subtypes are still loading, please wait</span>
            </div>
          </div>
          <div
            v-else
            class="overflow-x-auto rounded-2xl shadow-xl bg-white border border-slate-200"
          >
            <table class="min-w-full text-sm text-left">
              <thead class="bg-indigo-50 text-indigo-800 sticky top-0 z-10">
                <tr>
                  <th class="px-4 py-3 font-semibold">Name</th>
                  <th class="px-4 py-3 font-semibold">Default Charge-Out Rate</th>
                  <th class="px-4 py-3 font-semibold text-center">Workshop</th>
                  <th class="px-4 py-3 font-semibold text-center">Counts for Scheduling</th>
                  <th class="px-4 py-3 font-semibold text-center">Active</th>
                  <th class="px-4 py-3 font-semibold text-center">Display Order</th>
                  <th class="px-4 py-3 font-semibold text-center">Actions</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100 max-h-[60vh] overflow-y-auto">
                <tr
                  v-for="subtype in subtypes"
                  :key="subtype.id"
                  class="hover:bg-indigo-50 transition"
                  :class="{ 'opacity-50': !subtype.is_active }"
                >
                  <td class="px-4 py-3">{{ subtype.name }}</td>
                  <td class="px-4 py-3">{{ formatRate(subtype.default_charge_out_rate) }}</td>
                  <td class="px-4 py-3 text-center">
                    <span v-if="subtype.is_workshop" class="text-green-600">✔️</span>
                  </td>
                  <td class="px-4 py-3 text-center">
                    <span v-if="subtype.counts_for_scheduling" class="text-green-600">✔️</span>
                  </td>
                  <td class="px-4 py-3 text-center">
                    <span v-if="subtype.is_active" class="text-green-600">✔️</span>
                    <span v-else class="text-slate-400">Inactive</span>
                  </td>
                  <td class="px-4 py-3 text-center">{{ subtype.display_order }}</td>
                  <td class="px-4 py-3 text-center">
                    <button
                      @click="editSubtype(subtype)"
                      class="inline-flex items-center p-1 text-indigo-600 hover:text-indigo-900 transition-colors duration-150 hover:scale-110 active:scale-95"
                      aria-label="Edit"
                    >
                      <PencilLine class="w-5 h-5" />
                    </button>
                    <button
                      v-if="subtype.is_active"
                      @click="confirmDeactivate(subtype)"
                      class="inline-flex items-center p-1 text-amber-600 hover:text-amber-800 ml-2 transition-colors duration-150 hover:scale-110 active:scale-95"
                      aria-label="Deactivate"
                    >
                      <Ban class="w-5 h-5" />
                    </button>
                  </td>
                </tr>
                <tr v-if="!subtypes.length">
                  <td colspan="7" class="text-center py-8 text-slate-400 text-lg">
                    No labour subtypes found.
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
      <LabourSubtypeFormModal
        v-if="showModal"
        :subtype="selectedSubtype"
        @close="closeModal"
        @saved="onSaved"
      />
      <ConfirmModal
        v-if="showConfirm"
        title="Confirm Deactivation"
        :message="`Are you sure you want to deactivate ${selectedSubtype?.name}? It will no longer be selectable on new lines.`"
        @close="closeConfirm"
        @confirm="deactivateSubtype"
      />
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import AppLayout from '@/components/AppLayout.vue'
import Button from '@/components/ui/button/Button.vue'
import { ref, onMounted } from 'vue'
import { useLabourSubtypesApi } from '@/composables/useLabourSubtypesApi'
import LabourSubtypeFormModal from '@/components/LabourSubtypeFormModal.vue'
import ConfirmModal from '@/components/ConfirmModal.vue'
import { schemas } from '@/api/generated/api'
import { PencilLine, Ban, Wrench } from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import type { z } from 'zod'

type LabourSubtype = z.infer<typeof schemas.LabourSubtypeManage>

const { listLabourSubtypes, updateLabourSubtype } = useLabourSubtypesApi()
const subtypes = ref<LabourSubtype[]>([])
const loading = ref(true)
const showModal = ref(false)
const showConfirm = ref(false)
const selectedSubtype = ref<LabourSubtype | null>(null)

function formatRate(rate: number): string {
  return `$${rate.toFixed(2)}`
}

/**
 * Pull DRF field-level validation messages out of a 400 response body shaped
 * like {"is_active": ["N staff default to '<name>'; reassign them ..."]}.
 */
function extractFieldErrors(e: unknown): string | null {
  if (!e || typeof e !== 'object' || !('isAxiosError' in e)) return null
  const axiosError = e as { response?: { data?: unknown } }
  const data = axiosError.response?.data
  if (!data || typeof data !== 'object') return null
  const messages: string[] = []
  for (const value of Object.values(data as Record<string, unknown>)) {
    if (Array.isArray(value)) {
      messages.push(...value.map((v) => String(v)))
    } else if (typeof value === 'string') {
      messages.push(value)
    } else {
      // Non-string, non-array field value — ignore; not a user-facing message.
    }
  }
  return messages.length ? messages.join('\n') : null
}

function openCreate() {
  selectedSubtype.value = null
  showModal.value = true
}
function editSubtype(subtype: LabourSubtype) {
  selectedSubtype.value = subtype
  showModal.value = true
}
function closeModal() {
  showModal.value = false
  selectedSubtype.value = null
}
function onSaved() {
  fetchSubtypes()
  closeModal()
}
function confirmDeactivate(subtype: LabourSubtype) {
  selectedSubtype.value = subtype
  showConfirm.value = true
}
function closeConfirm() {
  showConfirm.value = false
  selectedSubtype.value = null
}
async function deactivateSubtype() {
  if (!selectedSubtype.value) return
  try {
    await updateLabourSubtype(selectedSubtype.value.id, { is_active: false })
    toast.success('Labour subtype deactivated.')
    fetchSubtypes()
  } catch (e) {
    const fieldErrors = extractFieldErrors(e)
    toast.error(fieldErrors ?? (e instanceof Error ? e.message : 'Failed to deactivate subtype.'))
  } finally {
    closeConfirm()
  }
}

async function fetchSubtypes() {
  loading.value = true
  subtypes.value = await listLabourSubtypes()
  loading.value = false
}
onMounted(fetchSubtypes)
</script>

<style scoped>
table {
  border-collapse: separate;
  border-spacing: 0;
  width: 100%;
}

thead th {
  position: sticky;
  top: 0;
  background: #eef2ff;
  z-index: 1;
}

tbody {
  max-height: 60vh;
  overflow-y: auto;
}

tr {
  transition: background 0.15s;
}

tr:hover {
  background: #f1f5f9;
}
</style>
