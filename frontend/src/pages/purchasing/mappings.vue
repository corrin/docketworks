<template>
  <AppLayout>
    <div class="p-4 md:p-8 space-y-4">
      <div class="flex items-center justify-between">
        <h1 class="text-xl font-bold flex items-center gap-2">
          <Package class="w-6 h-6 text-indigo-600" /> Product Mappings
        </h1>
        <div class="text-sm text-gray-600">
          <span class="font-medium">{{ unvalidatedCount }}</span> unvalidated /
          <span class="font-medium">{{ totalCount }}</span> total
        </div>
      </div>

      <div class="flex items-center gap-4">
        <div class="relative flex-1 max-w-md">
          <Search
            class="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-4 h-4"
          />
          <input
            v-model="searchTerm"
            type="text"
            placeholder="Search in original product data..."
            class="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
          />
        </div>
      </div>

      <div v-if="loading" class="flex justify-center items-center py-12">
        <Loader2 class="w-8 h-8 animate-spin text-indigo-600" />
      </div>

      <div v-else-if="error" class="rounded-lg bg-red-50 p-4 text-red-800">
        <p class="font-medium">Error loading product mappings</p>
        <p class="text-sm">{{ error }}</p>
      </div>

      <div
        v-else
        class="overflow-y-auto max-h-[70.3vh] lg:max-h-[80vh] xl:max-h-[85vh] rounded-2xl shadow-lg border"
      >
        <table class="min-w-full text-sm">
          <thead class="bg-slate-50 border-b sticky top-0">
            <tr>
              <th class="p-3 text-left font-semibold">Status</th>
              <th class="p-3 text-left font-semibold">Original Data</th>
              <th class="p-3 text-left font-semibold">Mapped Item Code</th>
              <th class="p-3 text-left font-semibold">Mapped Description</th>
              <th class="p-3 text-left font-semibold">Unit Cost</th>
              <th class="p-3 text-left font-semibold">In Xero</th>
              <th class="p-3 w-24 text-center font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="mapping in filteredMappings"
              :key="mapping.id"
              class="border-b hover:bg-slate-50"
              :class="{ 'bg-yellow-50': !mapping.is_validated }"
            >
              <td class="p-3">
                <span
                  v-if="!mapping.is_validated"
                  class="px-2 py-1 text-xs font-medium rounded-full bg-yellow-100 text-yellow-800"
                >
                  Needs Parsing Review
                </span>
                <span
                  v-else-if="mapping.mapped_item_code && mapping.item_code_is_in_xero"
                  class="px-2 py-1 text-xs font-medium rounded-full bg-green-100 text-green-800"
                >
                  Mapped to Xero
                </span>
                <span
                  v-else
                  class="px-2 py-1 text-xs font-medium rounded-full bg-blue-100 text-blue-800"
                >
                  Parsing OK
                </span>
              </td>
              <td class="p-3 max-w-xs truncate" :title="formatInputData(mapping.input_data)">
                {{ formatInputData(mapping.input_data) }}
              </td>
              <td class="p-3">{{ mapping.mapped_item_code || '-' }}</td>
              <td class="p-3 max-w-xs truncate" :title="mapping.mapped_description || ''">
                {{ mapping.mapped_description || '-' }}
              </td>
              <td class="p-3">
                {{ mapping.mapped_unit_cost ? formatCurrency(mapping.mapped_unit_cost) : '-' }}
                <span v-if="mapping.mapped_price_unit" class="text-gray-500 text-xs">
                  / {{ mapping.mapped_price_unit }}
                </span>
              </td>
              <td class="p-3">
                <span
                  v-if="mapping.item_code_is_in_xero"
                  class="inline-flex items-center text-green-600"
                >
                  <CheckCircle class="w-4 h-4" />
                </span>
                <span v-else class="inline-flex items-center text-gray-400">
                  <XCircle class="w-4 h-4" />
                </span>
              </td>
              <td class="p-3 flex justify-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  @click="openValidationDialog(mapping)"
                  class="w-8 h-8 p-0"
                  aria-label="Validate Mapping"
                >
                  <Edit class="w-4 h-4" />
                </Button>
              </td>
            </tr>
          </tbody>
        </table>

        <div v-if="filteredMappings.length === 0" class="text-center py-12 text-gray-500">
          <Package class="w-12 h-12 mx-auto mb-3 opacity-50" />
          <p>{{ searchTerm ? 'No mappings match your search' : 'No product mappings found' }}</p>
        </div>
      </div>
    </div>

    <!-- Validation Dialog -->
    <Dialog v-model:open="isDialogOpen">
      <DialogContent class="!max-w-6xl max-h-[95vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Validate Product Parsing</DialogTitle>
          <DialogDescription>
            Review the AI-parsed fields and add/update the Xero item code if available
          </DialogDescription>
        </DialogHeader>

        <div v-if="selectedMapping" class="space-y-4">
          <div class="bg-gray-50 p-3 rounded-lg">
            <p class="text-sm font-medium text-gray-700 mb-1">Original Data:</p>
            <p class="text-sm text-gray-600">{{ formatInputData(selectedMapping.input_data) }}</p>
          </div>

          <div class="bg-blue-50 border border-blue-200 rounded-lg p-3">
            <label class="block text-sm font-medium text-blue-900 mb-1">
              Xero Item Code (optional)
            </label>
            <input
              v-model="validationForm.mapped_item_code"
              type="text"
              placeholder="Add after creating in Xero"
              class="w-full px-3 py-2 border border-blue-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white"
            />
          </div>

          <div class="border-t pt-4 mb-2">
            <p class="text-sm font-medium text-gray-700 mb-3">Parsed Product Details</p>
          </div>

          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">
                Price Unit <span class="text-red-500">*</span>
              </label>
              <input
                v-model="validationForm.mapped_price_unit"
                type="text"
                placeholder="e.g., EA, M, KG"
                class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                required
              />
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Unit Cost</label>
              <input
                v-model.number="validationForm.mapped_unit_cost"
                type="number"
                step="0.01"
                class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
              />
            </div>
          </div>

          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">
              Description <span class="text-red-500">*</span>
            </label>
            <input
              v-model="validationForm.mapped_description"
              type="text"
              class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
              required
            />
          </div>

          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Metal Type</label>
              <input
                v-model="validationForm.mapped_metal_type"
                type="text"
                class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
              />
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Alloy</label>
              <input
                v-model="validationForm.mapped_alloy"
                type="text"
                class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
              />
            </div>
          </div>

          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">Specifics</label>
            <input
              v-model="validationForm.mapped_specifics"
              type="text"
              class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
            />
          </div>

          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">Dimensions</label>
            <input
              v-model="validationForm.mapped_dimensions"
              type="text"
              class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
            />
          </div>

          <div class="border-t pt-4 mt-2">
            <label class="block text-sm font-medium text-gray-700 mb-1">Validation Notes</label>
            <textarea
              v-model="validationForm.validation_notes"
              rows="3"
              placeholder="Optional notes about parsing corrections or mapping decisions..."
              class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" @click="isDialogOpen = false"> Cancel </Button>
          <Button @click="submitValidation" :disabled="isSubmitting">
            <Loader2 v-if="isSubmitting" class="w-4 h-4 mr-2 animate-spin" />
            {{ isSubmitting ? 'Validating...' : 'Validate' }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { toast } from 'vue-sonner'
import AppLayout from '@/components/AppLayout.vue'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Package, Search, Edit, Loader2, CheckCircle, XCircle } from 'lucide-vue-next'
import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import { z } from 'zod'
import { formatCurrency } from '@/utils/string-formatting'

type ProductMapping = z.infer<typeof schemas.ProductMapping>
type ProductMappingValidateRequest = z.infer<typeof schemas.ProductMappingValidateRequest>

const loading = ref(true)
const error = ref<string | null>(null)
const mappings = ref<ProductMapping[]>([])
const totalCount = ref(0)
const validatedCount = ref(0)
const unvalidatedCount = ref(0)
const searchTerm = ref('')
const isDialogOpen = ref(false)
const isSubmitting = ref(false)
const selectedMapping = ref<ProductMapping | null>(null)
const validationForm = ref<ProductMappingValidateRequest>({})

const filteredMappings = computed(() => {
  if (!searchTerm.value.trim()) {
    return mappings.value
  }

  const term = searchTerm.value.toLowerCase()
  return mappings.value.filter((mapping) => {
    const inputData = formatInputData(mapping.input_data).toLowerCase()
    return inputData.includes(term)
  })
})

const formatInputData = (data: unknown): string => {
  if (!data) return ''
  if (typeof data === 'string') return data
  if (typeof data === 'object') return JSON.stringify(data)
  return String(data)
}

const loadMappings = async () => {
  loading.value = true
  error.value = null

  try {
    const response = await api.listProductMappings()
    mappings.value = response.items
    totalCount.value = response.total_count
    validatedCount.value = response.validated_count
    unvalidatedCount.value = response.unvalidated_count
  } catch (err) {
    console.error('Failed to load product mappings:', err)
    error.value = err instanceof Error ? err.message : 'Unknown error occurred'
    toast.error('Failed to load product mappings')
  } finally {
    loading.value = false
  }
}

const openValidationDialog = (mapping: ProductMapping) => {
  selectedMapping.value = mapping
  validationForm.value = {
    mapped_item_code: mapping.mapped_item_code || '',
    mapped_description: mapping.mapped_description || '',
    mapped_metal_type: mapping.mapped_metal_type || '',
    mapped_alloy: mapping.mapped_alloy || '',
    mapped_specifics: mapping.mapped_specifics || '',
    mapped_dimensions: mapping.mapped_dimensions || '',
    mapped_unit_cost: mapping.mapped_unit_cost || null,
    mapped_price_unit: mapping.mapped_price_unit || '',
    validation_notes: mapping.validation_notes || '',
  }
  isDialogOpen.value = true
}

const submitValidation = async () => {
  if (!selectedMapping.value) return

  // Basic validation
  if (!validationForm.value.mapped_description?.trim()) {
    toast.error('Description is required')
    return
  }
  if (!validationForm.value.mapped_price_unit?.trim()) {
    toast.error('Price unit is required')
    return
  }

  isSubmitting.value = true

  try {
    const response = await api.validateProductMapping(validationForm.value, {
      params: {
        mapping_id: selectedMapping.value.id,
      },
    })

    if (response.success) {
      toast.success(response.message || 'Mapping validated successfully')
      if (response.updated_products_count) {
        toast.info(`Updated ${response.updated_products_count} product(s)`)
      }
      isDialogOpen.value = false
      selectedMapping.value = null
      await loadMappings()
    } else {
      toast.error(response.message || 'Failed to validate mapping')
    }
  } catch (err) {
    console.error('Failed to validate mapping:', err)
    toast.error('Failed to validate mapping')
  } finally {
    isSubmitting.value = false
  }
}

onMounted(() => {
  loadMappings()
})
</script>
