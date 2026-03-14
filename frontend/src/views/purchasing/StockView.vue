<template>
  <AppLayout>
    <div class="p-4 md:p-8 space-y-4">
      <div class="flex items-center justify-between">
        <h1 class="text-xl font-bold flex items-center gap-2">
          <Box class="w-6 h-6 text-indigo-600" /> Stock
        </h1>
        <Button @click="openAdd"> <PlusCircle class="w-4 h-4 mr-2" /> Add Stock </Button>
      </div>

      <!-- Search Field -->
      <div class="w-full max-w-md">
        <Input v-model="searchQuery" placeholder="Search stock items..." class="w-full" />
      </div>

      <!-- Stock Table -->
      <div class="overflow-x-auto overflow-y-auto max-h-[67vh] rounded-2xl shadow-lg border">
        <table class="min-w-full text-sm">
          <thead class="bg-slate-50 border-b">
            <tr>
              <th class="p-3 text-left font-semibold">Item Code</th>
              <th class="p-3 text-left font-semibold">Description</th>
              <th class="p-3 text-left font-semibold">Quantity</th>
              <th class="p-3 text-left font-semibold">Unit Cost</th>
              <th class="p-3 text-left font-semibold">Unit Revenue</th>
              <th class="p-3 w-24 text-center font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in pagedItems" :key="item.id" class="border-b hover:bg-slate-50">
              <td class="p-3">{{ item.item_code || '-' }}</td>
              <td class="p-3">{{ item.description }}</td>
              <td class="p-3">{{ formatQuantity(item.quantity) }}</td>
              <td class="p-3">{{ formatCurrency(item.unit_cost) }}</td>
              <td class="p-3">{{ formatCurrency(item.unit_revenue) }}</td>
              <td class="p-3 flex justify-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  @click="openAllocate(item)"
                  class="w-8 h-8 p-0"
                  aria-label="Allocate Stock"
                >
                  <Package class="w-4 h-4" />
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  @click="openDelete(item.id)"
                  class="w-8 h-8 p-0"
                  aria-label="Delete Stock"
                >
                  <Trash2 class="w-4 h-4 text-red-500" />
                </Button>
              </td>
            </tr>
            <tr v-if="filteredItems.length === 0 && !isLoading">
              <td colspan="6" class="p-8 text-center text-gray-500">No stock items found</td>
            </tr>
            <tr v-if="filteredItems.length === 0 && isLoading">
              <td colspan="6" class="p-8 text-center text-gray-500">
                <div class="flex items-center justify-center gap-2">
                  <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
                  Stock items are still loading, please wait
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <div class="flex justify-center mt-2">
        <Pagination
          :page="page"
          :total="totalPages"
          @update:page="page = $event"
          class="space-x-2"
          btn-class="px-3 py-1 rounded-lg border bg-white hover:bg-slate-100 text-sm font-medium"
          active-btn-class="bg-indigo-600 text-white border-indigo-600"
        />
      </div>
    </div>

    <!-- Allocate Modal -->
    <Dialog :open="showAllocate" @update:open="showAllocate = $event">
      <DialogContent class="max-w-md">
        <DialogHeader>
          <DialogTitle>Allocate Stock</DialogTitle>
        </DialogHeader>
        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium mb-1">Description</label>
            <Input v-model="allocateForm.description" />
          </div>
          <div>
            <label class="block text-sm font-medium mb-1">Available Quantity</label>
            <input
              :value="formatQuantity(allocateForm.availableQty)"
              readonly
              class="w-full px-3 py-2 border border-gray-300 rounded-md bg-gray-50 focus:outline-none"
              placeholder="0.00"
            />
            <!-- Debug: {{ allocateForm.availableQty }} -->
          </div>
          <div>
            <label class="block text-sm font-medium mb-1">Unit Cost</label>
            <Input v-model.number="allocateForm.unitCost" type="number" step="0.01" />
          </div>
          <div>
            <label class="block text-sm font-medium mb-1">Assign to Job</label>
            <select
              v-model="allocateForm.jobId"
              class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="">Select a job...</option>
              <option v-for="job in jobs" :key="job.id" :value="job.id">
                {{ job.name }}
              </option>
            </select>
          </div>
          <div>
            <label class="block text-sm font-medium mb-1">Quantity to Use</label>
            <Input v-model.number="allocateForm.qtyToUse" type="number" step="0.01" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="showAllocate = false">
            <X class="w-4 h-4 mr-2" /> Cancel
          </Button>
          <Button @click="submitAllocate"> <Check class="w-4 h-4 mr-2" /> Save </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- Add Stock Modal -->
    <Dialog :open="showAdd" @update:open="showAdd = $event">
      <DialogContent class="max-w-md">
        <DialogHeader>
          <DialogTitle>Add Stock</DialogTitle>
        </DialogHeader>
        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium mb-1">Description</label>
            <Input v-model="addForm.description" />
          </div>
          <div>
            <label class="block text-sm font-medium mb-1">Quantity</label>
            <Input v-model.number="addForm.quantity" type="number" step="0.01" />
          </div>
          <div>
            <label class="block text-sm font-medium mb-1">Unit Cost</label>
            <Input v-model.number="addForm.unitCost" type="number" step="0.01" />
          </div>
          <div>
            <label class="block text-sm font-medium mb-1">Metal Type</label>
            <Input v-model="addForm.metalType" />
          </div>
          <div>
            <label class="block text-sm font-medium mb-1">Alloy</label>
            <Input v-model="addForm.alloy" />
          </div>
          <div>
            <label class="block text-sm font-medium mb-1">Specifics</label>
            <Input v-model="addForm.specifics" />
          </div>
          <div>
            <label class="block text-sm font-medium mb-1">Location</label>
            <Input v-model="addForm.location" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="showAdd = false">
            <X class="w-4 h-4 mr-2" /> Cancel
          </Button>
          <Button @click="submitAdd"> <Check class="w-4 h-4 mr-2" /> Save </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- Delete Confirmation Modal -->
    <Dialog :open="showDelete" @update:open="showDelete = $event">
      <DialogContent class="max-w-md">
        <DialogHeader>
          <DialogTitle>Delete Stock</DialogTitle>
        </DialogHeader>
        <p class="mb-4">
          Are you sure you want to delete this stock item? This action cannot be undone.
        </p>
        <DialogFooter>
          <Button variant="outline" @click="showDelete = false">
            <X class="w-4 h-4 mr-2" /> Cancel
          </Button>
          <Button variant="destructive" @click="submitDelete">
            <Trash2 class="w-4 h-4 mr-2" /> Delete
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- Insufficient Stock Confirmation Modal -->
    <Dialog
      :open="showInsufficientStockConfirm"
      @update:open="showInsufficientStockConfirm = $event"
    >
      <DialogContent class="max-w-md">
        <DialogHeader>
          <DialogTitle>Insufficient Stock Warning</DialogTitle>
        </DialogHeader>
        <p class="mb-4">
          You are trying to consume
          <span class="font-semibold">{{ allocateForm.qtyToUse }}</span>
          units of <span class="font-semibold">{{ allocateForm.description }}</span
          >, but only <span class="font-semibold">{{ allocateForm.availableQty }}</span>
          units are available.
        </p>
        <p class="mb-4 text-amber-600">
          This will put the stock level to
          <span class="font-semibold">{{ allocateForm.availableQty - allocateForm.qtyToUse }}</span>
          units (negative stock).
        </p>
        <p class="mb-4">Do you want to continue anyway?</p>
        <DialogFooter>
          <Button variant="outline" @click="showInsufficientStockConfirm = false">
            <X class="w-4 h-4 mr-2" /> Cancel
          </Button>
          <Button variant="destructive" @click="performStockAllocation">
            <Check class="w-4 h-4 mr-2" /> Continue Anyway
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </AppLayout>
</template>
<script setup lang="ts">
import { debugLog } from '@/utils/debug'

import AppLayout from '@/components/AppLayout.vue'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import Pagination from '@/components/ui/pagination/Pagination.vue'
import { Box, PlusCircle, Package, Trash2, X, Check } from 'lucide-vue-next'
import { useStockStore, type StockItem } from '@/stores/stockStore'
import { useJobsStore } from '@/stores/jobs'
import { jobService } from '@/services/job.service'
import { onMounted, ref, computed, watch } from 'vue'
import { toast } from 'vue-sonner'
import { formatCurrency } from '@/utils/string-formatting'

const stockStore = useStockStore()
const jobsStore = useJobsStore()

const items = computed(() => stockStore.items)
const isLoading = computed(() => stockStore.loading)
const jobs = computed(() => jobsStore.allKanbanJobs)

const searchQuery = ref('')
const page = ref(1)
const pageSize = 25

const normalizeForSearch = (value?: string | null): string => (value ?? '').toLowerCase()

const filteredItems = computed(() => {
  if (!searchQuery.value.trim()) {
    return items.value
  }
  const query = searchQuery.value.toLowerCase()
  return items.value.filter(
    (item) =>
      normalizeForSearch(item.description).includes(query) ||
      normalizeForSearch(item.metal_type as string).includes(query) ||
      normalizeForSearch(item.alloy).includes(query) ||
      normalizeForSearch(item.specifics).includes(query) ||
      normalizeForSearch(item.location).includes(query),
  )
})

const totalPages = computed(() => Math.max(1, Math.ceil(filteredItems.value.length / pageSize)))

const pagedItems = computed(() => {
  const start = (page.value - 1) * pageSize
  return filteredItems.value.slice(start, start + pageSize)
})

watch(searchQuery, () => {
  page.value = 1
})

watch(
  () => filteredItems.value.length,
  () => {
    if (page.value > totalPages.value) {
      page.value = Math.max(1, totalPages.value)
    }
  },
)

const showAllocate = ref(false)
const showAdd = ref(false)
const showDelete = ref(false)
const showInsufficientStockConfirm = ref(false)
const activeId = ref<string>('')

const allocateForm = ref({
  description: '',
  availableQty: 0,
  unitCost: 0,
  jobId: '',
  qtyToUse: 0,
})

watch(
  allocateForm,
  (newValue) => {
    debugLog('allocateForm changed:', newValue)
  },
  { deep: true },
)

const addForm = ref({
  description: '',
  quantity: 0,
  unitCost: 0,
  metalType: '',
  alloy: '',
  specifics: '',
  location: '',
})

function formatQuantity(value: number): string {
  return isNaN(value) ? '0.00' : value.toFixed(2)
}

function openAllocate(item: StockItem) {
  allocateForm.value = {
    description: item.description,
    availableQty: item.quantity || 0,
    unitCost: item.unit_cost || 0,
    jobId: '',
    qtyToUse: 0,
  }

  activeId.value = item.id
  showAllocate.value = true
}

function openAdd() {
  addForm.value = {
    description: '',
    quantity: 0,
    unitCost: 0,
    metalType: '',
    alloy: '',
    specifics: '',
    location: '',
  }
  showAdd.value = true
}

function openDelete(id: string) {
  activeId.value = id
  showDelete.value = true
}

async function submitAllocate() {
  if (!allocateForm.value.jobId) {
    toast.error('Please select a job')
    return
  }

  if (allocateForm.value.qtyToUse <= 0) {
    toast.error('Quantity to use must be greater than 0')
    return
  }

  console.log('Stock allocation check:', {
    qtyToUse: allocateForm.value.qtyToUse,
    availableQty: allocateForm.value.availableQty,
    qtyToUseType: typeof allocateForm.value.qtyToUse,
    availableQtyType: typeof allocateForm.value.availableQty,
    comparison: allocateForm.value.qtyToUse > allocateForm.value.availableQty,
  })

  if (allocateForm.value.qtyToUse > allocateForm.value.availableQty) {
    // Show confirmation dialog for insufficient stock
    console.log('Should show insufficient stock dialog')
    showInsufficientStockConfirm.value = true
    return
  }

  await performStockAllocation()
}

async function performStockAllocation() {
  try {
    await stockStore.consumeStock(activeId.value, {
      job_id: allocateForm.value.jobId,
      quantity: allocateForm.value.qtyToUse,
    })
    toast.success('Stock allocated successfully')
    showAllocate.value = false
    showInsufficientStockConfirm.value = false
    await stockStore.fetchStock()
  } catch (error) {
    toast.error('Failed to allocate stock')
    debugLog('Error allocating stock:', error)
  }
}

async function submitAdd() {
  if (!addForm.value.description || addForm.value.quantity <= 0 || addForm.value.unitCost < 0) {
    toast.error('Please fill in all required fields with valid values')
    return
  }

  try {
    await stockStore.create({
      description: addForm.value.description,
      quantity: addForm.value.quantity,
      unit_cost: addForm.value.unitCost,
      metal_type: addForm.value.metalType,
      alloy: addForm.value.alloy,
      specifics: addForm.value.specifics,
      location: addForm.value.location,
      source: 'manual',
    })
    toast.success('Stock added successfully')
    showAdd.value = false
    await stockStore.fetchStock()
  } catch (error) {
    toast.error('Failed to add stock')
    debugLog('Error adding stock:', error)
  }
}

async function submitDelete() {
  try {
    await stockStore.deactivate(activeId.value)
    toast.success('Stock deleted successfully')
    showDelete.value = false
    await stockStore.fetchStock()
  } catch (error) {
    toast.error('Failed to delete stock')
    debugLog('Error deleting stock:', error)
  }
}

onMounted(async () => {
  await Promise.all([stockStore.fetchStock(), loadJobs()])
})

async function loadJobs() {
  try {
    const data = await jobService.getAllJobs()
    // Use the correct property names from FetchAllJobsResponse schema
    const activeJobs = data.active_jobs || []
    const archivedJobs = data.archived_jobs || []
    jobsStore.setKanbanJobs([...activeJobs, ...archivedJobs])
  } catch (error) {
    debugLog('Error loading jobs:', error)
    toast.error('Failed to load jobs')
  }
}
</script>
