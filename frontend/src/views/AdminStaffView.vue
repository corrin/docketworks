<template>
  <AppLayout>
    <div class="w-full h-full flex flex-col overflow-hidden">
      <div class="flex-1 overflow-y-auto p-0">
        <div class="max-w-5xl mx-auto py-8 px-2 md:px-8 h-full flex flex-col gap-8">
          <div class="flex items-center justify-between mb-2">
            <h1 class="text-3xl font-extrabold text-indigo-700 flex items-center gap-3">
              <svg
                class="w-8 h-8 text-indigo-400 animate-pulse"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <circle cx="12" cy="12" r="10" stroke-width="2" />
                <path d="M12 6v6l4 2" stroke-width="2" />
              </svg>
              Staff Management
            </h1>
            <Button
              variant="default"
              class="text-lg px-6 py-3"
              data-automation-id="AdminStaffView-new-staff"
              @click="openCreate"
            >
              New Staff
            </Button>
          </div>
          <div v-if="loading" class="flex-1 flex items-center justify-center">
            <div class="flex items-center space-x-2 text-lg text-gray-600">
              <div class="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500"></div>
              <span>Staff members are still loading, please wait</span>
            </div>
          </div>
          <div
            v-else
            class="overflow-x-auto rounded-2xl shadow-xl bg-white border border-slate-200"
          >
            <table class="min-w-full text-sm text-left">
              <thead class="bg-indigo-50 text-indigo-800 sticky top-0 z-10">
                <tr>
                  <th class="px-4 py-3 font-semibold">Icon</th>
                  <th class="px-4 py-3 font-semibold">First Name</th>
                  <th class="px-4 py-3 font-semibold">Last Name</th>
                  <th class="px-4 py-3 font-semibold">Is Office Staff</th>
                  <th class="px-4 py-3 font-semibold">Is SuperUser</th>
                  <th class="px-4 py-3 font-semibold">Last Login</th>
                  <th class="px-4 py-3 font-semibold">Date Joined</th>
                  <th class="px-4 py-3 font-semibold text-center">Actions</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100 max-h-[60vh] overflow-y-auto">
                <tr
                  v-for="staff in filteredStaff"
                  :key="staff.id"
                  class="hover:bg-indigo-50 transition"
                >
                  <td class="px-4 py-3">
                    <div
                      class="w-10 h-10 rounded-full bg-indigo-100 flex items-center justify-center text-lg font-bold text-indigo-700 border-2 border-indigo-300 overflow-hidden"
                    >
                      <template v-if="staff.icon_url">
                        <img
                          :src="staff.icon_url"
                          alt="Profile image"
                          class="object-cover w-full h-full"
                        />
                      </template>
                      <template v-else>
                        {{ (staff.first_name?.[0] || '?') + (staff.last_name?.[0] || '') }}
                      </template>
                    </div>
                  </td>
                  <td class="px-4 py-3">{{ staff.first_name }}</td>
                  <td class="px-4 py-3">{{ staff.last_name }}</td>
                  <td class="px-4 py-3 text-center">
                    <span v-if="staff.is_office_staff" class="text-green-600">✔️</span>
                  </td>
                  <td class="px-4 py-3 text-center">
                    <span v-if="staff.is_superuser" class="text-green-600">✔️</span>
                  </td>
                  <td class="px-4 py-3">{{ formatDate(staff.last_login) }}</td>
                  <td class="px-4 py-3">{{ formatDate(staff.date_joined) }}</td>
                  <td class="px-4 py-3 text-center">
                    <button
                      @click="editStaff(staff)"
                      class="inline-flex items-center p-1 text-indigo-600 hover:text-indigo-900 transition-colors duration-150 hover:scale-110 active:scale-95"
                      aria-label="Edit"
                    >
                      <PencilLine class="w-5 h-5" />
                    </button>
                    <button
                      @click="confirmDelete(staff)"
                      class="inline-flex items-center p-1 text-red-500 hover:text-red-700 ml-2 transition-colors duration-150 hover:scale-110 active:scale-95"
                      aria-label="Delete"
                    >
                      <Trash2 class="w-5 h-5" />
                    </button>
                  </td>
                </tr>
                <tr v-if="!filteredStaff.length">
                  <td colspan="9" class="text-center py-8 text-slate-400 text-lg">
                    No staff found for the current search criteria.
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
      <StaffFormModal
        v-if="showModal"
        :staff="selectedStaff"
        @close="closeModal"
        @saved="onSaved"
      />
      <ConfirmModal
        v-if="showConfirm"
        title="Confirm Deletion"
        :message="`Are you sure you want to delete ${selectedStaff?.first_name} ${selectedStaff?.last_name}? This action cannot be undone.`"
        @close="closeConfirm"
        @confirm="deleteStaff"
      />
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import AppLayout from '@/components/AppLayout.vue'
import Button from '@/components/ui/button/Button.vue'
import { ref, computed, onMounted } from 'vue'
import { useStaffApi } from '@/composables/useStaffApi'
import StaffFormModal from '@/components/StaffFormModal.vue'
import ConfirmModal from '@/components/ConfirmModal.vue'
import { schemas } from '@/api/generated/api'
import { PencilLine, Trash2 } from 'lucide-vue-next'
import type { z } from 'zod'

type Staff = z.infer<typeof schemas.Staff>

const { listStaff, removeStaff } = useStaffApi()
const staffList = ref<Staff[]>([])
const loading = ref(true)
const search = ref('')
const showModal = ref(false)
const showConfirm = ref(false)
const selectedStaff = ref<Staff | null>(null)

const filteredStaff = computed(() =>
  !search.value
    ? staffList.value
    : staffList.value.filter((s: Staff) =>
        [
          s.first_name,
          s.last_name,
          s.preferred_name,
          s.email,
          s.base_wage_rate,
          s.xero_user_id,
          s.hours_mon,
          s.hours_tue,
          s.hours_wed,
          s.hours_thu,
          s.hours_fri,
          s.hours_sat,
          s.hours_sun,
          s.is_office_staff,
          s.date_left,
          s.is_superuser,
          s.groups,
          s.user_permissions,
          s.last_login,
          s.date_joined,
        ]
          .map((v) => String(v ?? ''))
          .join(' ')
          .toLowerCase()
          .includes(search.value.toLowerCase()),
      ),
)

function openCreate() {
  selectedStaff.value = null
  showModal.value = true
}
function editStaff(staff: Staff) {
  console.log('AdminStaffView - Editing staff:', staff)
  selectedStaff.value = staff
  showModal.value = true
}
function closeModal() {
  showModal.value = false
  selectedStaff.value = null
}
function onSaved() {
  fetchStaff()
  closeModal()
}
function confirmDelete(staff: Staff) {
  selectedStaff.value = staff
  showConfirm.value = true
}
function closeConfirm() {
  showConfirm.value = false
  selectedStaff.value = null
}
async function deleteStaff() {
  if (!selectedStaff.value) return
  await removeStaff(selectedStaff.value.id)
  fetchStaff()
  closeConfirm()
}

async function fetchStaff() {
  loading.value = true
  // For admin view, show all staff including those without valid payroll IDs
  staffList.value = await listStaff()
  console.log('AdminStaffView - Staff data received from API:', staffList.value)
  loading.value = false
}
onMounted(fetchStaff)

function formatDate(dateStr: string | null | undefined) {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  return date.toLocaleString('en-NZ', {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
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
