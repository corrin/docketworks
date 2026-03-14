import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { schemas } from '@/api/generated/api'
import { api } from '@/api/client'
import { debugLog } from '@/utils/debug'
import type { z } from 'zod'

type CostSet = z.infer<typeof schemas.CostSet>
type CostLine = z.infer<typeof schemas.CostLine>
type CostLineMeta = {
  category?: string
  labour_minutes?: number
}

function createEmptyGrouping() {
  return {
    time: [] as CostLine[],
    material: [] as CostLine[],
    adjust: [] as CostLine[],
  }
}

function getCategoryFromKind(kind: string, metaCategory?: string): 'time' | 'material' | 'adjust' {
  if (metaCategory) {
    const normalizedCategory = metaCategory.toLowerCase()
    switch (normalizedCategory) {
      case 'fabrication':
        return 'time'
      case 'mainwork':
        return 'material'
    }
  }

  const normalizedKind = kind.toLowerCase()
  switch (normalizedKind) {
    case 'time':
      return 'time'
    case 'adjust':
    case 'adjustment':
      return 'adjust'
    case 'material':
    default:
      return 'material'
  }
}

export const useCostingStore = defineStore('costing', () => {
  const currentKind = ref<'estimate' | 'quote' | 'actual'>('estimate')
  const costSet = ref<CostSet | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const load = async (jobId: string, kind?: 'estimate' | 'quote' | 'actual') => {
    loading.value = true
    error.value = null

    const targetKind = kind || currentKind.value

    try {
      debugLog(`Loading costing data for job ${jobId}, kind: ${targetKind}`)

      const data = await api.job_rest_jobs_cost_sets_retrieve({
        params: {
          id: jobId,
          kind: targetKind,
        },
      })
      costSet.value = data

      currentKind.value = targetKind

      debugLog('Costing data loaded successfully')
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Failed to load costing data'
      debugLog(`Error loading costing data for ${targetKind}:`, err)

      if (error.value) {
        throw err
      }
    } finally {
      loading.value = false
    }
  }

  const setCurrentKind = async (kind: 'estimate' | 'quote' | 'actual', jobId?: string) => {
    const previousKind = currentKind.value
    currentKind.value = kind

    if (jobId && previousKind !== kind) {
      try {
        await load(jobId, kind)
      } catch {
        debugLog(`Failed to load ${kind} data, keeping current data`)
      }
    }
  }

  const clearData = () => {
    costSet.value = null
    error.value = null
  }

  const groupedByKind = computed(() => {
    if (!costSet.value || !costSet.value.cost_lines) {
      return createEmptyGrouping()
    }
    return costSet.value.cost_lines.reduce((groups, costLine) => {
      const kind = costLine.kind || ''
      const meta = costLine.meta as CostLineMeta | undefined
      const metaCategory = meta?.category

      const category = getCategoryFromKind(kind, metaCategory)
      groups[category].push(costLine)
      return groups
    }, createEmptyGrouping())
  })

  function sumCostLines(fn: (cl: CostLine) => number) {
    if (!costSet.value || !costSet.value.cost_lines) return 0
    return costSet.value.cost_lines.reduce((acc, cl) => acc + (fn(cl) || 0), 0)
  }

  const totalCost = computed(() => {
    if (
      costSet.value &&
      costSet.value.summary &&
      typeof costSet.value.summary.cost === 'number' &&
      !isNaN(costSet.value.summary.cost) &&
      costSet.value.summary.cost > 0
    ) {
      return costSet.value.summary.cost
    }

    return sumCostLines((cl) => cl.total_cost || 0)
  })

  const totalRevenue = computed(() => {
    if (
      costSet.value &&
      costSet.value.summary &&
      typeof costSet.value.summary.rev === 'number' &&
      !isNaN(costSet.value.summary.rev) &&
      costSet.value.summary.rev > 0
    ) {
      return costSet.value.summary.rev
    }

    return sumCostLines((cl) => cl.total_rev || 0)
  })

  const totalHours = computed(() => {
    if (
      costSet.value &&
      costSet.value.summary &&
      typeof costSet.value.summary.hours === 'number' &&
      !isNaN(costSet.value.summary.hours) &&
      costSet.value.summary.hours > 0
    ) {
      return costSet.value.summary.hours
    }

    return sumCostLines((cl) => {
      const meta = cl.meta as CostLineMeta | undefined
      const isTimeEntry =
        meta?.category === 'fabrication' || String(cl.kind || '').toLowerCase() === 'time'

      if (isTimeEntry) {
        if (typeof meta?.labour_minutes === 'number') {
          return meta.labour_minutes / 60
        }

        return cl.quantity || 0
      }
      return 0
    })
  })

  const isLoaded = computed(() => costSet.value !== null)

  return {
    currentKind,
    costSet,
    loading,
    error,

    load,
    setCurrentKind,
    clearData,

    groupedByKind,
    totalCost,
    totalRevenue,
    totalHours,
    isLoaded,
  }
})
