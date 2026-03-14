<template>
  <div class="kpi-card" :class="{ 'kpi-card--clickable': clickable }" @click="handleClick">
    <div class="kpi-card__header">
      <h3 class="kpi-card__title">{{ title }}</h3>
      <div v-if="trend" class="kpi-card__trend" :class="trendClass">
        <component :is="trendIcon" class="w-3 h-3" />
        <span class="text-xs font-medium">{{ trend }}</span>
      </div>
    </div>

    <div class="kpi-card__content">
      <div class="kpi-card__value">{{ value }}</div>
      <div v-if="subtitle" class="kpi-card__subtitle">
        <template v-if="Array.isArray(subtitle)">
          <div v-for="(line, i) in subtitle" :key="i">{{ line }}</div>
        </template>
        <template v-else>{{ subtitle }}</template>
      </div>
    </div>

    <div v-if="percentage" class="kpi-card__footer">
      <div class="kpi-card__percentage" :class="percentageClass">
        {{ percentage }}
      </div>
      <div v-if="description" class="kpi-card__description">{{ description }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { TrendingUp, TrendingDown, Minus } from 'lucide-vue-next'

interface Props {
  title: string
  value: string
  subtitle?: string | string[]
  percentage?: string
  description?: string
  trend?: string
  trendDirection?: 'up' | 'down' | 'neutral'
  variant?: 'default' | 'success' | 'warning' | 'danger'
  clickable?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  trendDirection: 'neutral',
  variant: 'default',
  clickable: false,
})

const emit = defineEmits<{
  click: []
}>()

function handleClick() {
  if (props.clickable) {
    emit('click')
  }
}

const trendIcon = computed(() => {
  switch (props.trendDirection) {
    case 'up':
      return TrendingUp
    case 'down':
      return TrendingDown
    default:
      return Minus
  }
})

const trendClass = computed(() => {
  return {
    'kpi-card__trend--up': props.trendDirection === 'up',
    'kpi-card__trend--down': props.trendDirection === 'down',
    'kpi-card__trend--neutral': props.trendDirection === 'neutral',
  }
})

const percentageClass = computed(() => {
  return {
    'kpi-card__percentage--success': props.variant === 'success',
    'kpi-card__percentage--warning': props.variant === 'warning',
    'kpi-card__percentage--danger': props.variant === 'danger',
  }
})
</script>

<style scoped>
@reference 'tailwindcss';

.kpi-card {
  @apply bg-white rounded-lg border border-gray-200 p-6 shadow-sm;
  min-height: 160px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.kpi-card--clickable {
  @apply cursor-pointer transition-all duration-200 hover:shadow-md hover:border-blue-300;
}

.kpi-card__header {
  @apply flex items-start justify-between mb-4;
}

.kpi-card__title {
  @apply text-sm font-medium text-gray-600;
}

.kpi-card__trend {
  @apply flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium;
}

.kpi-card__trend--up {
  @apply bg-green-100 text-green-700;
}

.kpi-card__trend--down {
  @apply bg-red-100 text-red-700;
}

.kpi-card__trend--neutral {
  @apply bg-gray-100 text-gray-700;
}

.kpi-card__content {
  @apply flex-1;
}

.kpi-card__value {
  @apply text-2xl font-bold text-gray-900 mb-1;
}

.kpi-card__subtitle {
  @apply text-sm text-gray-500;
}

.kpi-card__footer {
  @apply flex items-center justify-between mt-4 pt-3 border-t border-gray-100;
}

.kpi-card__percentage {
  @apply font-semibold text-sm;
}

.kpi-card__percentage--success {
  @apply text-green-600;
}

.kpi-card__percentage--warning {
  @apply text-yellow-600;
}

.kpi-card__percentage--danger {
  @apply text-red-600;
}

.kpi-card__description {
  @apply text-xs text-gray-500;
}
</style>
