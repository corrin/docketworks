# Component Architecture

## Component Hierarchy

### Directory Structure

```
src/components/
├── ui/                 # Base UI components (all from shadcn-vue)
├── job/                # Job-specific components
├── timesheet/          # Timesheet-related components
├── kanban/             # Kanban board components
├── purchasing/         # Purchasing components
├── quote/              # Quoting components
├── shared/             # Shared components
└── icons/              # Icon components
```

### Component Types

#### 1. Base UI Components (shadcn-vue)

- All components inside `components/ui` are directly generated and maintained via **shadcn-vue**.
- These are reusable, presentation-focused components with no business logic.
- They follow shadcn-vue and Tailwind CSS patterns for consistency and accessibility.

```vue
<!-- components/ui/Button.vue (shadcn-vue) -->
<template>
  <button
    :class="buttonVariants({ variant, size })"
    :disabled="disabled"
    @click="$emit('click', $event)"
  >
    <slot />
  </button>
</template>

<script setup lang="ts">
import { cva } from 'class-variance-authority'

interface Props {
  variant?: 'default' | 'destructive' | 'outline' | 'secondary' | 'ghost' | 'link'
  size?: 'default' | 'sm' | 'lg' | 'icon'
  disabled?: boolean
}

defineProps<Props>()
defineEmits<{
  click: [event: MouseEvent]
}>()

const buttonVariants = cva(
  'inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors',
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground hover:bg-primary/90',
        destructive: 'bg-destructive text-destructive-foreground hover:bg-destructive/90',
        // ... other variants
      },
      size: {
        default: 'h-10 px-4 py-2',
        sm: 'h-9 rounded-md px-3',
        lg: 'h-11 rounded-md px-8',
        icon: 'h-10 w-10',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
)
</script>
```

#### 2. Functional Components

- Contain specific business logic
- Use composables for shared logic
- Integrate with stores and APIs

```vue
<!-- components/job/JobCard.vue -->
<template>
  <Card class="job-card">
    <CardHeader>
      <CardTitle>{{ job.job_number }}</CardTitle>
      <CardDescription>{{ job.client_name }}</CardDescription>
    </CardHeader>

    <CardContent>
      <div class="space-y-2">
        <div class="flex justify-between">
          <span>Status:</span>
          <Badge :variant="getStatusVariant(job.status)">
            {{ getStatusLabel(job.status) }}
          </Badge>
        </div>

        <div class="flex justify-between">
          <span>Prazo:</span>
          <span>{{ formatDate(job.due_date) }}</span>
        </div>
      </div>
    </CardContent>

    <CardFooter>
      <Button @click="$emit('edit', job)" size="sm"> Editar </Button>
      <Button @click="$emit('view', job)" variant="outline" size="sm"> Ver Detalhes </Button>
    </CardFooter>
  </Card>
</template>

<script setup lang="ts">
import type { Job } from '@/api/generated/api'
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useJobHelpers } from '@/composables/useJobHelpers'

interface Props {
  job: Job
}

interface Emits {
  edit: [job: Job]
  view: [job: Job]
}

defineProps<Props>()
defineEmits<Emits>()

const { getStatusVariant, getStatusLabel, formatDate } = useJobHelpers()
</script>
```

#### 3. Layout Components

- Structure pages and sections
- Manage navigation and responsive layout

```vue
<!-- components/shared/PageLayout.vue -->
<template>
  <div class="page-layout">
    <header class="page-header">
      <h1 class="page-title">{{ title }}</h1>
      <div class="page-actions">
        <slot name="actions" />
      </div>
    </header>

    <main class="page-content">
      <slot />
    </main>
  </div>
</template>

<script setup lang="ts">
interface Props {
  title: string
}

defineProps<Props>()
</script>
```

## Composition Patterns

### Typed Props and Emits

```typescript
// Always define interfaces for complex props
interface JobFormProps {
  job?: Job
  mode: 'create' | 'edit'
  loading?: boolean
}

interface JobFormEmits {
  submit: [data: CreateJobRequest | UpdateJobRequest]
  cancel: []
  'update:loading': [loading: boolean]
}

const props = defineProps<JobFormProps>()
const emit = defineEmits<JobFormEmits>()
```

### Typed Slots

```vue
<template>
  <div class="data-table">
    <slot name="header" :columns="columns" :sort="sort" :on-sort="handleSort" />

    <slot name="row" v-for="item in items" :key="item.id" :item="item" :index="index" />
  </div>
</template>

<script setup lang="ts" generic="T">
interface Props {
  items: T[]
  columns: TableColumn[]
}

interface Emits {
  sort: [column: string, direction: 'asc' | 'desc']
}
</script>
```

### Composables in Components

```vue
<script setup lang="ts">
onMounted(() => {
// Use composables for shared logic
const { jobs, loading, error, fetchJobs } = useJobData()
const { filters, applyFilters, resetFilters } = useJobFilters()
const { selectedJobs, selectJob, selectAll } = useJobSelection()

// Component-specific logic
const showCreateDialog = ref(false)

const handleCreateJob = async (data: CreateJobRequest) => {
  try {
    await createJob(data)
    showCreateDialog.value = false
    await fetchJobs()
  } catch (error) {
    // Error handling
  }
}

onMounted(() => {
  fetchJobs()
})
</script>
```

## Styling Patterns

### Tailwind CSS Classes

```vue
<template>
  <!-- Use Tailwind utility classes -->
  <div class="flex items-center justify-between p-4 bg-white rounded-lg shadow-sm border">
    <h2 class="text-lg font-semibold text-gray-900">
      {{ title }}
    </h2>

    <Button class="ml-4" :class="{ 'opacity-50': loading }" :disabled="loading">
      {{ loading ? 'Loading...' : 'Save' }}
    </Button>
  </div>
</template>
```

### Variants with CVA

```typescript
import { cva } from 'class-variance-authority'

const cardVariants = cva('rounded-lg border bg-card text-card-foreground shadow-sm', {
  variants: {
    variant: {
      default: 'border-border',
      destructive: 'border-destructive/50 text-destructive',
      success: 'border-green-200 bg-green-50 text-green-800',
    },
    size: {
      sm: 'p-3',
      default: 'p-6',
      lg: 'p-8',
    },
  },
  defaultVariants: {
    variant: 'default',
    size: 'default',
  },
})
```

## Accessibility

### ARIA Labels and Roles

```vue
<template>
  <div role="tablist" aria-label="Job navigation" class="tab-list">
    <button
      v-for="tab in tabs"
      :key="tab.id"
      role="tab"
      :aria-selected="activeTab === tab.id"
      :aria-controls="`panel-${tab.id}`"
      @click="setActiveTab(tab.id)"
    >
      {{ tab.label }}
    </button>
  </div>

  <div
    v-for="tab in tabs"
    :key="tab.id"
    :id="`panel-${tab.id}`"
    role="tabpanel"
    :hidden="activeTab !== tab.id"
  >
    <slot :name="tab.id" />
  </div>
</template>
```

### Keyboard Navigation

```vue
<script setup lang="ts">
const handleKeydown = (event: KeyboardEvent) => {
  switch (event.key) {
    case 'ArrowRight':
      nextTab()
      break
    case 'ArrowLeft':
      previousTab()
      break
    case 'Home':
      firstTab()
      break
    case 'End':
      lastTab()
      break
  }
}
</script>
```

## Performance

### Lazy Loading

```vue
<script setup lang="ts">
// Lazy load heavy components
const HeavyChart = defineAsyncComponent(() => import('./HeavyChart.vue'))
const showChart = ref(false)
</script>

<template>
  <div>
    <Button @click="showChart = true">Show Chart</Button>

    <Suspense v-if="showChart">
      <template #default>
        <HeavyChart :data="chartData" />
      </template>
      <template #fallback>
        <div>Loading chart...</div>
      </template>
    </Suspense>
  </div>
</template>
```

### Virtual Scrolling

```vue
<!-- For large lists -->
<template>
  <VirtualList :items="jobs" :item-height="80" :container-height="400">
    <template #default="{ item }">
      <JobCard :job="item" />
    </template>
  </VirtualList>
</template>
```

## Component Testing

### Test Structure

```typescript
import { mount } from '@vue/test-utils'
import { describe, it, expect } from 'vitest'
import JobCard from '@/components/job/JobCard.vue'

describe('JobCard', () => {
  const mockJob = {
    id: '1',
    job_number: 'JOB-001',
    client_name: 'Test Client',
    status: 'active',
    due_date: '2024-12-31',
  }

  it('renders job information correctly', () => {
    const wrapper = mount(JobCard, {
      props: { job: mockJob },
    })

    expect(wrapper.text()).toContain('JOB-001')
    expect(wrapper.text()).toContain('Test Client')
  })

  it('emits edit event when edit button is clicked', async () => {
    const wrapper = mount(JobCard, {
      props: { job: mockJob },
    })

    await wrapper.find('[data-testid="edit-button"]').trigger('click')

    expect(wrapper.emitted('edit')).toBeTruthy()
    expect(wrapper.emitted('edit')?.[0]).toEqual([mockJob])
  })
})
```

## Related References

- See: [03-frontend-development.md](./03-frontend-development.md)
- See: [06-state-management.md](./06-state-management.md)
- See: [09-performance-optimization.md](./09-performance-optimization.md)
- See: [12-testing-protocols.md](./12-testing-protocols.md)
