<template>
  <AppLayout>
    <div class="p-4 md:p-8 space-y-4">
      <!-- Header -->
      <div class="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <h1 class="text-xl font-bold flex items-center gap-2">
          <Users class="w-6 h-6 text-indigo-600" />
          Companies
        </h1>
        <Button @click="openCreateModal">
          <PlusCircle class="w-4 h-4 mr-2" />
          New Company
        </Button>
      </div>

      <!-- Search Input -->
      <div class="relative flex-1 max-w-md">
        <Search class="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-4 h-4" />
        <input
          v-model="searchInput"
          type="text"
          placeholder="Search companies by name or email..."
          data-automation-id="CompaniesTable-search"
          class="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
          @input="onSearchInput"
        />
      </div>

      <!-- Loading State -->
      <div v-if="companyStore.isLoading" class="flex items-center justify-center py-12">
        <Loader2 class="w-8 h-8 animate-spin text-indigo-600" />
        <span class="ml-3 text-gray-600">Loading companies...</span>
      </div>

      <!-- No Companies -->
      <div
        v-else-if="!companyStore.hasCompanies && !companyStore.searchQuery"
        class="text-center py-12 text-gray-500"
      >
        <Users class="w-12 h-12 mx-auto mb-4 text-gray-400" />
        <p class="text-lg font-medium">No companies yet</p>
        <p class="text-sm">Click "New Company" to add your first company</p>
      </div>

      <!-- No Results after search -->
      <div
        v-else-if="!companyStore.hasCompanies && companyStore.searchQuery"
        class="text-center py-12 text-gray-500"
      >
        <Search class="w-12 h-12 mx-auto mb-4 text-gray-400" />
        <p class="text-lg font-medium">No companies found</p>
        <p class="text-sm">Try a different search term</p>
      </div>

      <!-- Results Table -->
      <div v-else class="space-y-4">
        <div class="text-sm text-gray-600">
          {{
            companyStore.searchQuery
              ? `Found ${companyStore.totalCount}`
              : `Showing ${companyStore.totalCount}`
          }}
          company{{ companyStore.totalCount !== 1 ? 's' : '' }}
        </div>

        <div class="overflow-y-auto max-h-[70vh] rounded-2xl shadow-lg border border-gray-200">
          <table class="min-w-full text-sm" data-automation-id="CompaniesTable-table">
            <thead class="bg-slate-50 border-b sticky top-0">
              <tr>
                <th class="p-3 text-left">
                  <button
                    @click="toggleSort('name')"
                    data-automation-id="CompaniesTable-header-name"
                    class="flex items-center gap-1 font-semibold text-gray-700 hover:text-indigo-600 transition-colors cursor-pointer"
                  >
                    Company Name
                    <ArrowUpDown v-if="companyStore.sortBy !== 'name'" class="w-4 h-4" />
                    <ArrowUp
                      v-else-if="companyStore.sortDir === 'asc'"
                      class="w-4 h-4 text-indigo-600"
                    />
                    <ArrowDown v-else class="w-4 h-4 text-indigo-600" />
                  </button>
                </th>
                <th class="p-3 text-left font-semibold text-gray-700">Email</th>
                <th class="p-3 text-left">
                  <button
                    @click="toggleSort('total_spend')"
                    data-automation-id="CompaniesTable-header-total-spend"
                    class="flex items-center gap-1 font-semibold text-gray-700 hover:text-indigo-600 transition-colors cursor-pointer"
                  >
                    Total Spend
                    <ArrowUpDown v-if="companyStore.sortBy !== 'total_spend'" class="w-4 h-4" />
                    <ArrowUp
                      v-else-if="companyStore.sortDir === 'asc'"
                      class="w-4 h-4 text-indigo-600"
                    />
                    <ArrowDown v-else class="w-4 h-4 text-indigo-600" />
                  </button>
                </th>
                <th class="p-3 text-left">
                  <button
                    @click="toggleSort('last_invoice_date')"
                    data-automation-id="CompaniesTable-header-last-invoice"
                    class="flex items-center gap-1 font-semibold text-gray-700 hover:text-indigo-600 transition-colors cursor-pointer"
                  >
                    Last Invoice
                    <ArrowUpDown
                      v-if="companyStore.sortBy !== 'last_invoice_date'"
                      class="w-4 h-4"
                    />
                    <ArrowUp
                      v-else-if="companyStore.sortDir === 'asc'"
                      class="w-4 h-4 text-indigo-600"
                    />
                    <ArrowDown v-else class="w-4 h-4 text-indigo-600" />
                  </button>
                </th>
                <th class="p-3 text-left font-semibold text-gray-700">Type</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(company, index) in companyStore.companies"
                :key="company.id"
                class="border-b hover:bg-slate-50 cursor-pointer transition-colors"
                :data-automation-id="`CompaniesTable-row-${company.id}`"
                :data-company-id="company.id"
                @click="navigateToCompany(company, index + 1)"
              >
                <td
                  class="p-3 font-medium text-gray-900"
                  :data-automation-id="`CompaniesTable-cell-${company.id}-name`"
                >
                  {{ company.name }}
                </td>
                <td
                  class="p-3 text-gray-600"
                  :data-automation-id="`CompaniesTable-cell-${company.id}-email`"
                >
                  {{ company.email || '-' }}
                </td>
                <td
                  class="p-3 text-gray-900 font-medium"
                  :data-automation-id="`CompaniesTable-cell-${company.id}-total-spend`"
                >
                  {{ company.total_spend || '$0.00' }}
                </td>
                <td
                  class="p-3 text-gray-600"
                  :data-automation-id="`CompaniesTable-cell-${company.id}-last-invoice`"
                >
                  {{ formatDate(company.last_invoice_date) }}
                </td>
                <td class="p-3" :data-automation-id="`CompaniesTable-cell-${company.id}-type`">
                  <Badge :variant="company.is_account_customer ? 'default' : 'secondary'">
                    {{ company.is_account_customer ? 'Account' : 'Cash' }}
                  </Badge>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Pagination -->
        <Pagination
          v-if="companyStore.totalPages > 1"
          v-model:page="currentPage"
          :total="companyStore.totalPages"
          :sibling-count="1"
        />
      </div>
    </div>

    <!-- Create Company Modal -->
    <CreateCompanyModal
      :is-open="isCreateModalOpen"
      @close="isCreateModalOpen = false"
      @company-created="handleCompanyCreated"
    />
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useCompanyStore } from '@/stores/companyStore'
import { logCompanySearchClick } from '@/composables/useCompanyLookup'
import type { Company } from '@/composables/useCompanyLookup'
import { useDebounceFn } from '@vueuse/core'
import AppLayout from '@/components/AppLayout.vue'
import CreateCompanyModal from '@/components/CreateCompanyModal.vue'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import Pagination from '@/components/ui/pagination/Pagination.vue'
import {
  Users,
  Search,
  PlusCircle,
  Loader2,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
} from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import { formatDate } from '@/utils/string-formatting'

const router = useRouter()
const companyStore = useCompanyStore()

// Local state
const searchInput = ref('')
const isCreateModalOpen = ref(false)
const currentPage = ref(1)

// Debounced search
const debouncedSearch = useDebounceFn(async (query: string) => {
  currentPage.value = 1
  await companyStore.fetchCompanies({ query, page: 1 })
}, 300)

function onSearchInput() {
  debouncedSearch(searchInput.value)
}

// Sort handling - server-side
type SortField = 'name' | 'total_spend' | 'last_invoice_date'

async function toggleSort(field: SortField) {
  let newDir: 'asc' | 'desc' = 'asc'

  if (companyStore.sortBy === field) {
    // Same field - toggle direction
    newDir = companyStore.sortDir === 'asc' ? 'desc' : 'asc'
  }

  await companyStore.fetchCompanies({ sortBy: field, sortDir: newDir, page: 1 })
  currentPage.value = 1
}

// Page change - server-side
watch(currentPage, async (newPage) => {
  await companyStore.fetchCompanies({ page: newPage })
  window.scrollTo({ top: 0, behavior: 'smooth' })
})

function navigateToCompany(company: Company, rank: number) {
  logCompanySearchClick(company, companyStore.searchQuery, rank, 'crm_clients_table')
  router.push({ name: '/crm/companies/[id]', params: { id: company.id } })
}

function openCreateModal() {
  isCreateModalOpen.value = true
}

async function handleCompanyCreated(company: { id?: string }) {
  isCreateModalOpen.value = false
  toast.success('Company created successfully')

  // Reload current page to include the new company
  await companyStore.fetchCompanies({})

  // Optionally navigate to the new company
  if (company?.id) {
    router.push({ name: '/crm/companies/[id]', params: { id: company.id } })
  }
}

// Load first page on mount
onMounted(async () => {
  try {
    await companyStore.fetchCompanies({ page: 1, sortBy: 'name', sortDir: 'asc' })
  } catch (error) {
    toast.error('Failed to load companies')
    console.error('Load companies error:', error)
  }
})
</script>
