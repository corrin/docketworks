<template>
  <Dialog :open="isOpen" @update:open="(open) => !open && $emit('close')">
    <DialogContent class="sm:max-w-4xl">
      <DialogHeader>
        <DialogTitle>Advanced Search</DialogTitle>
        <DialogDescription> Search jobs using detailed filters </DialogDescription>
      </DialogHeader>

      <div class="space-y-4">
        <!-- Universal Search -->
        <div class="bg-blue-50 border border-blue-200 rounded-lg p-4">
          <label class="block text-sm font-medium text-blue-800 mb-1"> Search All Fields </label>
          <input
            v-model="localFilters.q"
            type="text"
            class="w-full px-3 py-2 border border-blue-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
            placeholder="Search job number, name, description, or client..."
          />
          <p class="mt-1 text-xs text-blue-600">
            Searches across job number, name, description, and client name
          </p>
        </div>

        <!-- Individual Field Filters -->
        <div class="border-t pt-4">
          <p class="text-xs text-gray-500 mb-3">Or filter by specific fields:</p>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">Job Number</label>
            <input
              v-model="localFilters.job_number"
              type="text"
              class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
              placeholder="Enter job number"
            />
          </div>

          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">Job Name</label>
            <input
              v-model="localFilters.name"
              type="text"
              class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
              placeholder="Enter job name"
            />
          </div>

          <div>
            <ClientLookup
              id="client"
              label="Client"
              v-model="localFilters.client_name"
              placeholder="Search for a client..."
              :search-mode="true"
            />
          </div>

          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">Contact Person</label>
            <input
              v-model="localFilters.contact_person"
              type="text"
              class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
              placeholder="Contact person"
            />
          </div>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">Description</label>
            <input
              v-model="localFilters.description"
              type="text"
              class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
              placeholder="Job description"
            />
          </div>
          <div>
            <StatusMultiSelect v-model="localFilters.status" label="Status" />
          </div>

          <div>
            <StaffDropdown id="createdBy" label="Created By" v-model="localFilters.created_by" />
          </div>

          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">Payment Status</label>
            <select
              v-model="localFilters.paid"
              class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
            >
              <option value="">Any</option>
              <option value="true">Paid</option>
              <option value="false">Unpaid</option>
            </select>
          </div>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">Rejected Status</label>
            <select
              v-model="localFilters.rejected_flag"
              class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
            >
              <option value="">Any</option>
              <option value="true">Rejected</option>
              <option value="false">Not Rejected</option>
            </select>
          </div>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">Created After</label>
            <input
              v-model="localFilters.created_after"
              type="date"
              class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
            />
          </div>

          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">Created Before</label>
            <input
              v-model="localFilters.created_before"
              type="date"
              class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
            />
          </div>
        </div>
      </div>

      <div class="flex flex-col items-center justify-center">
        <div class="w-full max-w-xs">
          <label class="block text-sm font-medium text-gray-700 mb-1 text-center"
            >Xero Invoice (Number or ID)</label
          >
          <input
            v-model="localFilters.xero_invoice_params"
            type="text"
            class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
            placeholder="Xero Invoice"
          />
        </div>
      </div>

      <DialogFooter>
        <button
          type="button"
          class="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
          @click="clearFilters"
        >
          Clear All
        </button>

        <button
          type="button"
          class="ml-3 px-4 py-2 text-sm font-medium text-white bg-blue-600 border border-transparent rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
          @click="handleSearch"
          :disabled="isLoading"
        >
          {{ isLoading ? 'Searching...' : 'Search' }}
        </button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import ClientLookup from '@/components/ClientLookup.vue'
import StaffDropdown from '@/components/StaffDropdown.vue'
import StatusMultiSelect from '@/components/StatusMultiSelect.vue'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { type AdvancedFilters, DEFAULT_ADVANCED_FILTERS } from '@/constants/advanced-filters'

interface Props {
  isOpen: boolean
  filters: AdvancedFilters
  isLoading?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  isLoading: false,
})

const emit = defineEmits<{
  close: []
  search: [filters: AdvancedFilters]
  'clear-filters': []
}>()

const localFilters = ref<AdvancedFilters>({ ...props.filters })

watch(
  () => props.filters,
  (newFilters) => {
    localFilters.value = { ...newFilters }
  },
  { deep: true },
)

const handleSearch = () => {
  emit('search', { ...localFilters.value })
  emit('close')
}

const clearFilters = () => {
  localFilters.value = { ...DEFAULT_ADVANCED_FILTERS }
  emit('clear-filters')
}
</script>
