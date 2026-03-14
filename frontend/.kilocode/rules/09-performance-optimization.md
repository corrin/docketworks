# Performance Optimization

## Performance Strategies

### Component Lazy Loading

```typescript
// Lazy loading for heavy components
const HeavyChart = defineAsyncComponent({
  loader: () => import('./HeavyChart.vue'),
  loadingComponent: () => h('div', 'Loading chart...'),
  errorComponent: () => h('div', 'Error loading chart'),
  delay: 200,
  timeout: 3000,
})

// Conditional lazy loading
const showAdvancedFeatures = ref(false)
const AdvancedPanel = computed(() =>
  showAdvancedFeatures.value ? defineAsyncComponent(() => import('./AdvancedPanel.vue')) : null,
)
```

### Route-based Code Splitting

```typescript
// router/index.ts
const routes = [
  {
    path: '/jobs',
    name: 'Jobs',
    component: () => import('@/views/JobsView.vue'),
    meta: { preload: true },
  },
  {
    path: '/timesheets',
    name: 'Timesheets',
    component: () => import('@/views/TimesheetsView.vue'),
  },
  {
    path: '/reports',
    name: 'Reports',
    component: () => import('@/views/ReportsView.vue'),
    meta: { requiresAuth: true, heavy: true },
  },
]

// Preload critical routes
router.beforeEach((to, from, next) => {
  if (to.meta?.preload) {
    // Preload component
  }
  next()
})
```

## Render Optimization

### Virtual Scrolling for Large Lists

```vue
<template>
  <div class="virtual-list-container" :style="{ height: containerHeight + 'px' }">
    <div class="virtual-list-spacer" :style="{ height: offsetY + 'px' }" />

    <div
      v-for="item in visibleItems"
      :key="item.id"
      class="virtual-list-item"
      :style="{ height: itemHeight + 'px' }"
    >
      <slot :item="item" :index="item.index" />
    </div>

    <div
      class="virtual-list-spacer"
      :style="{ height: totalHeight - offsetY - visibleHeight + 'px' }"
    />
  </div>
</template>

<script setup lang="ts" generic="T">
interface Props {
  items: T[]
  itemHeight: number
  containerHeight: number
}

const props = defineProps<Props>()

const scrollTop = ref(0)
const startIndex = computed(() => Math.floor(scrollTop.value / props.itemHeight))
const endIndex = computed(() =>
  Math.min(
    startIndex.value + Math.ceil(props.containerHeight / props.itemHeight) + 1,
    props.items.length,
  ),
)

const visibleItems = computed(() =>
  props.items.slice(startIndex.value, endIndex.value).map((item, index) => ({
    ...item,
    index: startIndex.value + index,
  })),
)

const totalHeight = computed(() => props.items.length * props.itemHeight)
const offsetY = computed(() => startIndex.value * props.itemHeight)
const visibleHeight = computed(() => (endIndex.value - startIndex.value) * props.itemHeight)
</script>
```

### Memoization of Computed Properties

```typescript
// Use computed for expensive derived values
const expensiveComputation = computed(() => {
  // Heavy calculation that only runs when dependencies change
  return jobs.value.reduce((acc, job) => {
    return acc + calculateJobProfit(job)
  }, 0)
})

// Manual memoization for very heavy calculations
const memoizedCalculation = useMemoize((data: ComplexData[]) => {
  return performHeavyCalculation(data)
})
```

### Debounce and Throttle

```typescript
import { debounce, throttle } from 'lodash-es'

// Debounce for search
const searchTerm = ref('')
const searchResults = ref([])

const debouncedSearch = debounce(async (term: string) => {
  if (!term.trim()) {
    searchResults.value = []
    return
  }

  try {
    const results = await searchJobs(term)
    searchResults.value = results
  } catch (error) {
    console.error('Erro na busca:', error)
  }
}, 300)

watch(searchTerm, debouncedSearch)

// Throttle for scroll events
const handleScroll = throttle((event: Event) => {
  const target = event.target as HTMLElement
  scrollTop.value = target.scrollTop
}, 16) // ~60fps
```

## Data Optimization

### Smart Cache

```typescript
class DataCache {
  private cache = new Map<string, { data: any; timestamp: number; ttl: number }>()

  set<T>(key: string, data: T, ttl = 5 * 60 * 1000) {
    this.cache.set(key, {
      data,
      timestamp: Date.now(),
      ttl,
    })
  }

  get<T>(key: string): T | null {
    const entry = this.cache.get(key)

    if (!entry) return null

    if (Date.now() - entry.timestamp > entry.ttl) {
      this.cache.delete(key)
      return null
    }

    return entry.data
  }

  invalidate(pattern?: string) {
    if (!pattern) {
      this.cache.clear()
      return
    }

    const regex = new RegExp(pattern)
    for (const key of this.cache.keys()) {
      if (regex.test(key)) {
        this.cache.delete(key)
      }
    }
  }
}

const dataCache = new DataCache()

// Usage in composable
export function useCachedJobData() {
  const fetchJobsWithCache = async (filters?: JobFilters) => {
    const cacheKey = `jobs:${JSON.stringify(filters || {})}`

    // Try cache first
    const cached = dataCache.get<Job[]>(cacheKey)
    if (cached) {
      return cached
    }

    // Fetch fresh data
    const jobs = await JobService.getInstance().fetchJobs(filters)

    // Cache for 5 minutes
    dataCache.set(cacheKey, jobs, 5 * 60 * 1000)

    return jobs
  }

  const invalidateJobCache = () => {
    dataCache.invalidate('jobs:')
  }

  return {
    fetchJobsWithCache,
    invalidateJobCache,
  }
}
```

### Efficient Pagination

```typescript
export function usePaginatedData<T>(
  fetcher: (page: number, pageSize: number) => Promise<PaginatedResponse<T>>,
  pageSize = 25,
) {
  const items = ref<T[]>([])
  const loading = ref(false)
  const hasMore = ref(true)
  const currentPage = ref(1)

  const loadMore = async () => {
    if (loading.value || !hasMore.value) return

    loading.value = true

    try {
      const response = await fetcher(currentPage.value, pageSize)

      if (currentPage.value === 1) {
        items.value = response.results
      } else {
        items.value.push(...response.results)
      }

      hasMore.value = !!response.next
      currentPage.value++
    } catch (error) {
      console.error('Error loading data:', error)
    } finally {
      loading.value = false
    }
  }

  const reset = () => {
    items.value = []
    currentPage.value = 1
    hasMore.value = true
  }

  return {
    items: readonly(items),
    loading: readonly(loading),
    hasMore: readonly(hasMore),
    loadMore,
    reset,
  }
}
```

## Bundle Optimization

### Tree Shaking

```typescript
// ✅ CORRECT - Specific import
import { debounce } from 'lodash-es'
import { format } from 'date-fns'

// ❌ INCORRECT - Full import
import _ from 'lodash'
import * as dateFns from 'date-fns'

// Vite config for tree shaking
// vite.config.ts
export default defineConfig({
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['vue', 'vue-router', 'pinia'],
          ui: ['reka-ui', 'lucide-vue-next'],
          utils: ['lodash-es', 'date-fns', 'zod'],
        },
      },
    },
  },
})
```

### Bundle Analysis

```bash
# Analyze bundle size
npm run build -- --analyze

# Or use rollup-plugin-visualizer
npm install --save-dev rollup-plugin-visualizer
```

## Image Optimization

### Image Lazy Loading

```vue
<template>
  <img v-if="shouldLoad" :src="src" :alt="alt" @load="onLoad" @error="onError" class="lazy-image" />
  <div v-else class="image-placeholder">
    <div class="loading-spinner" />
  </div>
</template>

<script setup lang="ts">
interface Props {
  src: string
  alt: string
}

const props = defineProps<Props>()
const shouldLoad = ref(false)
const imageRef = ref<HTMLElement>()

// Intersection Observer for lazy loading
onMounted(() => {
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          shouldLoad.value = true
          observer.disconnect()
        }
      })
    },
    { threshold: 0.1 },
  )

  if (imageRef.value) {
    observer.observe(imageRef.value)
  }
})
</script>
```

### Asset Optimization

```typescript
// Use dynamic imports for large assets
const loadLargeAsset = async () => {
  const { default: largeData } = await import('@/assets/large-dataset.json')
  return largeData
}

// Image compression
// Use tools like imagemin or sharp to optimize images
```

## Performance Monitoring

### Web Vitals

```typescript
import { getCLS, getFID, getFCP, getLCP, getTTFB } from 'web-vitals'

const reportWebVitals = (metric: any) => {
  // Send metrics to monitoring service
  console.log(metric)

  // In production, send to analytics
  if (import.meta.env.PROD) {
    // analytics.track('web-vital', metric)
  }
}

// Measure Core Web Vitals
getCLS(reportWebVitals)
getFID(reportWebVitals)
getFCP(reportWebVitals)
getLCP(reportWebVitals)
getTTFB(reportWebVitals)
```

### Performance Observer

```typescript
class PerformanceMonitor {
  private observer: PerformanceObserver | null = null

  start() {
    if (!('PerformanceObserver' in window)) return

    this.observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        this.handlePerformanceEntry(entry)
      }
    })

    this.observer.observe({
      entryTypes: ['navigation', 'resource', 'measure', 'paint'],
    })
  }

  private handlePerformanceEntry(entry: PerformanceEntry) {
    switch (entry.entryType) {
      case 'navigation':
        this.trackNavigation(entry as PerformanceNavigationTiming)
        break
      case 'resource':
        this.trackResource(entry as PerformanceResourceTiming)
        break
      case 'paint':
        this.trackPaint(entry)
        break
    }
  }

  private trackNavigation(entry: PerformanceNavigationTiming) {
    const metrics = {
      dns: entry.domainLookupEnd - entry.domainLookupStart,
      tcp: entry.connectEnd - entry.connectStart,
      request: entry.responseStart - entry.requestStart,
      response: entry.responseEnd - entry.responseStart,
      dom: entry.domContentLoadedEventEnd - entry.responseEnd,
      load: entry.loadEventEnd - entry.loadEventStart,
    }

    console.log('Navigation metrics:', metrics)
  }

  private trackResource(entry: PerformanceResourceTiming) {
    if (entry.duration > 1000) {
      // Slow resources > 1s
      console.warn('Slow resource:', entry.name, entry.duration)
    }
  }

  private trackPaint(entry: PerformanceEntry) {
    console.log(`${entry.name}: ${entry.startTime}ms`)
  }

  stop() {
    this.observer?.disconnect()
  }
}

// Initialize monitoring
const performanceMonitor = new PerformanceMonitor()
performanceMonitor.start()
```

## Memory Optimization

### Event Listener Cleanup

```typescript
export function useEventListener(
  target: EventTarget,
  event: string,
  handler: EventListener,
  options?: AddEventListenerOptions,
) {
  onMounted(() => {
    target.addEventListener(event, handler, options)
  })

  onUnmounted(() => {
    target.removeEventListener(event, handler, options)
  })
}

// Usage
const handleResize = () => {
  // Handle resize
}

useEventListener(window, 'resize', handleResize)
```

### Weak References for Cache

```typescript
class WeakCache {
  private cache = new WeakMap<object, any>()

  set(key: object, value: any) {
    this.cache.set(key, value)
  }

  get(key: object) {
    return this.cache.get(key)
  }

  has(key: object) {
    return this.cache.has(key)
  }
}

// Cache that does not prevent garbage collection
const componentCache = new WeakCache()
```

## Related References

- See: [06-state-management.md](./06-state-management.md)
- See: [07-component-architecture.md](./07-component-architecture.md)
- See: [05-api-integration.md](./05-api-integration.md)
