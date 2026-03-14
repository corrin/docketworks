<template>
  <div
    class="bg-white rounded-lg border border-gray-200 p-6 hover:shadow-lg transition-shadow duration-200"
  >
    <div class="flex items-center justify-between mb-4">
      <div class="flex items-center space-x-3">
        <div :class="getIconClass(color)" class="p-2 rounded-lg">
          <component :is="iconComponent" class="h-6 w-6" />
        </div>
        <div>
          <h3 class="text-lg font-semibold text-gray-900">{{ title }}</h3>
          <p class="text-sm text-gray-600">{{ subtitle }}</p>
        </div>
      </div>
    </div>

    <div class="mb-4">
      <div class="text-3xl font-bold" :class="getValueClass(color)">
        {{ value }}
      </div>
    </div>

    <div v-if="progress !== undefined" class="w-full bg-gray-200 rounded-full h-2">
      <div
        :class="getProgressClass(color)"
        class="h-2 rounded-full transition-all duration-300"
        :style="{ width: `${Math.min(100, Math.max(0, progress))}%` }"
      ></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Clock, TrendingUp, DollarSign, Users, AlertCircle, CheckCircle } from 'lucide-vue-next'

const props = withDefaults(
  defineProps<{
    title: string
    value: string
    subtitle?: string
    progress?: number
    icon: string
    color: 'blue' | 'green' | 'emerald' | 'purple' | 'amber' | 'red'
  }>(),
  {
    subtitle: '',
    progress: undefined,
  },
)

const iconMap = {
  Clock,
  TrendingUp,
  DollarSign,
  Users,
  AlertCircle,
  CheckCircle,
}

const iconComponent = computed(() => {
  return iconMap[props.icon as keyof typeof iconMap] || Clock
})

const getIconClass = (color: string): string => {
  const classes = {
    blue: 'bg-blue-100 text-blue-600',
    green: 'bg-green-100 text-green-600',
    emerald: 'bg-emerald-100 text-emerald-600',
    purple: 'bg-purple-100 text-purple-600',
    amber: 'bg-amber-100 text-amber-600',
    red: 'bg-red-100 text-red-600',
  }
  return classes[color as keyof typeof classes] || classes.blue
}

const getValueClass = (color: string): string => {
  const classes = {
    blue: 'text-blue-600',
    green: 'text-green-600',
    emerald: 'text-emerald-600',
    purple: 'text-purple-600',
    amber: 'text-amber-600',
    red: 'text-red-600',
  }
  return classes[color as keyof typeof classes] || classes.blue
}

const getProgressClass = (color: string): string => {
  const classes = {
    blue: 'bg-blue-500',
    green: 'bg-green-500',
    emerald: 'bg-emerald-500',
    purple: 'bg-purple-500',
    amber: 'bg-amber-500',
    red: 'bg-red-500',
  }
  return classes[color as keyof typeof classes] || classes.blue
}
</script>
