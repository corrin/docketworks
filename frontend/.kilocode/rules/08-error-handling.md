# Error Handling

## Error Handling Strategies

### Defensive Programming Philosophy

Following the backend philosophy: **fail early, no fallbacks, mandatory error persistence**

- Fail early and clearly
- Do not use fallbacks that mask problems
- Persist errors for analysis
- Always provide clear feedback to the user

### Error Types

#### 1. Validation Errors

```typescript
import { z } from 'zod'

const jobSchema = z.object({
  job_number: z.string().min(1, 'Job number is required'),
  client_name: z.string().min(1, 'Client name is required'),
  due_date: z.string().datetime('Date must be valid'),
})

const validateJobData = (data: unknown) => {
  try {
    return jobSchema.parse(data)
  } catch (error) {
    if (error instanceof z.ZodError) {
      const validationErrors = error.errors.reduce(
        (acc, err) => {
          acc[err.path.join('.')] = err.message
          return acc
        },
        {} as Record<string, string>,
      )

      throw new ValidationError('Invalid data', validationErrors)
    }
    throw error
  }
}
```

#### 2. State Errors

```typescript
class StateError extends Error {
  constructor(
    message: string,
    public context?: any,
  ) {
    super(message)
    this.name = 'StateError'
  }
}

// Usage example
const updateJobStatus = (jobId: string, newStatus: string) => {
  const job = jobs.value.find((j) => j.id === jobId)

  if (!job) {
    throw new StateError(`Job not found: ${jobId}`)
  }

  if (!isValidStatusTransition(job.status, newStatus)) {
    throw new StateError(`Invalid status transition: ${job.status} -> ${newStatus}`, {
      jobId,
      currentStatus: job.status,
      newStatus,
    })
  }

  job.status = newStatus
}
```

## Visual and Console Feedback for Errors

All errors must provide both visual feedback to the user and be logged to the browser console for debugging and monitoring purposes.

- Use the `toast` function from **vue-sonner** to display user-friendly error messages.
- Always log errors using `console.error`, `console.warn`, or `console.log` as appropriate, including relevant context and stack traces if available.
- Never suppress errors silently; always ensure both the user and the developer are informed.

**Example:**

```typescript
import { toast } from 'vue-sonner'

try {
  await someAsyncOperation()
  toast.success('Operation completed successfully!')
} catch (err) {
  toast.error('An error occurred. Please try again.')
  console.error('Operation failed:', err)
}
```

## Handling in Components

### Error Handler Composable

```typescript
export function useErrorHandler() {
  const error = ref<string | null>(null)
  const fieldErrors = ref<Record<string, string>>({})

  const handleError = (err: any) => {
    if (err instanceof ValidationError) {
      fieldErrors.value = err.fieldErrors
      error.value = err.message
    } else if (err.status === 422 && err.details) {
      // API validation errors
      fieldErrors.value = Object.entries(err.details).reduce(
        (acc, [key, messages]) => {
          acc[key] = Array.isArray(messages) ? messages[0] : messages
          return acc
        },
        {} as Record<string, string>,
      )
      error.value = 'Check the highlighted fields'
    } else {
      error.value = err.message || 'Unknown error'
      fieldErrors.value = {}
    }
  }

  const clearErrors = () => {
    error.value = null
    fieldErrors.value = {}
  }

  const hasFieldError = (field: string) => {
    return !!fieldErrors.value[field]
  }

  const getFieldError = (field: string) => {
    return fieldErrors.value[field]
  }

  return {
    error: readonly(error),
    fieldErrors: readonly(fieldErrors),
    handleError,
    clearErrors,
    hasFieldError,
    getFieldError,
  }
}
```

### Usage in Components

```vue
<template>
  <form @submit.prevent="handleSubmit">
    <!-- General error -->
    <Alert v-if="error" variant="destructive" class="mb-4">
      <AlertCircle class="h-4 w-4" />
      <AlertTitle>Error</AlertTitle>
      <AlertDescription>{{ error }}</AlertDescription>
    </Alert>

    <!-- Field with error -->
    <div class="space-y-2">
      <Label for="job_number">Job Number</Label>
      <Input
        id="job_number"
        v-model="formData.job_number"
        :class="{ 'border-destructive': hasFieldError('job_number') }"
      />
      <p v-if="hasFieldError('job_number')" class="text-sm text-destructive">
        {{ getFieldError('job_number') }}
      </p>
    </div>

    <Button type="submit" :disabled="loading">
      {{ loading ? 'Saving...' : 'Save' }}
    </Button>
  </form>
</template>

<script setup lang="ts">
const { error, fieldErrors, handleError, clearErrors, hasFieldError, getFieldError } =
  useErrorHandler()
const loading = ref(false)

const handleSubmit = async () => {
  clearErrors()
  loading.value = true

  try {
    await JobService.getInstance().createJob(formData)
    toast.success('Job created successfully!')
    // Redirect or reset form
  } catch (err) {
    handleError(err)
  } finally {
    loading.value = false
  }
}
</script>
```

## Loading and Error States

### Composable for Async States

```typescript
export function useAsyncOperation<T>() {
  const loading = ref(false)
  const error = ref<string | null>(null)
  const data = ref<T | null>(null)

  const execute = async (operation: () => Promise<T>) => {
    loading.value = true
    error.value = null

    try {
      data.value = await operation()
      return data.value
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Unknown error'
      throw err
    } finally {
      loading.value = false
    }
  }

  const reset = () => {
    loading.value = false
    error.value = null
    data.value = null
  }

  return {
    loading: readonly(loading),
    error: readonly(error),
    data: readonly(data),
    execute,
    reset,
  }
}
```

## Global Error Boundary

### Error Boundary Component

```vue
<!-- components/shared/ErrorBoundary.vue -->
<template>
  <div v-if="hasError" class="error-boundary">
    <Alert variant="destructive">
      <AlertTriangle class="h-4 w-4" />
      <AlertTitle>Something went wrong</AlertTitle>
      <AlertDescription>
        {{ errorMessage }}
      </AlertDescription>
    </Alert>

    <div class="mt-4 space-x-2">
      <Button @click="retry" variant="outline"> Try Again </Button>
      <Button @click="reportError" variant="secondary"> Report Error </Button>
    </div>
  </div>

  <slot v-else />
</template>

<script setup lang="ts">
const hasError = ref(false)
const errorMessage = ref('')
const errorDetails = ref<any>(null)

const handleError = (error: Error, errorInfo: any) => {
  hasError.value = true
  errorMessage.value = error.message
  errorDetails.value = { error, errorInfo }

  // Log the error
  console.error('Error Boundary caught an error:', error, errorInfo)

  // Send error to monitoring service
  // reportErrorToService(error, errorInfo)
}

const retry = () => {
  hasError.value = false
  errorMessage.value = ''
  errorDetails.value = null
}

const reportError = () => {
  // Implement error reporting
  toast.success('Error reported. Thank you!')
}

// Capture unhandled errors
onErrorCaptured((error, instance, info) => {
  handleError(error, { instance, info })
  return false // Prevent propagation
})
</script>
```

## Error Logging

### Logging System

```typescript
enum LogLevel {
  DEBUG = 0,
  INFO = 1,
  WARN = 2,
  ERROR = 3,
}

class Logger {
  private static instance: Logger
  private logLevel: LogLevel = LogLevel.INFO

  static getInstance(): Logger {
    if (!this.instance) {
      this.instance = new Logger()
    }
    return this.instance
  }

  private log(level: LogLevel, message: string, data?: any) {
    if (level < this.logLevel) return

    const timestamp = new Date().toISOString()
    const logEntry = {
      timestamp,
      level: LogLevel[level],
      message,
      data,
      url: window.location.href,
      userAgent: navigator.userAgent,
    }

    // Console log in development
    if (import.meta.env.DEV) {
      console.log(`[${LogLevel[level]}] ${message}`, data)
    }

    // Send to logging service in production
    if (import.meta.env.PROD && level >= LogLevel.ERROR) {
      this.sendToLoggingService(logEntry)
    }
  }

  error(message: string, data?: any) {
    this.log(LogLevel.ERROR, message, data)
  }

  warn(message: string, data?: any) {
    this.log(LogLevel.WARN, message, data)
  }

  info(message: string, data?: any) {
    this.log(LogLevel.INFO, message, data)
  }

  debug(message: string, data?: any) {
    this.log(LogLevel.DEBUG, message, data)
  }

  private async sendToLoggingService(logEntry: any) {
    try {
      // Implement sending to logging service
      // await api.post('/api/logs/', logEntry)
    } catch (error) {
      // Silent fail to avoid error loop
    }
  }
}

export const logger = Logger.getInstance()
```

## Performance Monitoring

### Error Metrics

```typescript
class ErrorMetrics {
  private static errorCounts = new Map<string, number>()
  private static errorTimes = new Map<string, number[]>()

  static recordError(type: string, message: string) {
    const key = `${type}:${message}`

    // Count occurrences
    this.errorCounts.set(key, (this.errorCounts.get(key) || 0) + 1)

    // Register time
    const times = this.errorTimes.get(key) || []
    times.push(Date.now())
    this.errorTimes.set(key, times)

    // Clean up old data (last 24h)
    const dayAgo = Date.now() - 24 * 60 * 60 * 1000
    this.errorTimes.set(
      key,
      times.filter((time) => time > dayAgo),
    )
  }

  static getErrorStats() {
    return {
      counts: Object.fromEntries(this.errorCounts),
      recentErrors: Object.fromEntries(this.errorTimes),
    }
  }
}
```

## Related References

- See: [05-api-integration.md](./05-api-integration.md)
- See: [04-authentication-security.md](./04-authentication-security.md)
- See: [06-state-management.md](./06-state-management.md)
- See: [11-documentation-standards.md](./11-documentation-standards.md)
