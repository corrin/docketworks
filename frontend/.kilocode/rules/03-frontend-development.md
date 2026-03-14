# Frontend Development Standards

## Required Technology Stack

### Core Technologies

- **Vue 3** with Composition API and `<script setup>`
- **TypeScript** for type safety
- **Vite** as build tool and dev server
- **Pinia** for state management
- **Vue Router** with authentication guards
- **Tailwind CSS v4** with custom theme
- **Axios** for HTTP requests with interceptors

### Main Libraries

- **AG Grid Community** - Data grids for timesheets
- **Reka UI** - Headless component library (shadcn/vue style)
- **VeeValidate + Zod** - Form validation
- **SortableJS** - Drag and drop functionality
- **Vue Sonner** - Toast notifications
- **Lucide Vue** - Icon library
- **shadcn-vue** - Component library based on TailwindCSS v4 (see summary below)

---

### Executive Summary: shadcn-vue

**shadcn-vue** is a community-driven Vue port of the popular shadcn/ui library (originally for React). It provides accessible, Tailwind-styled UI component templates that you copy into your project and customize as needed. Components are built using Radix Vue primitives for accessibility and flexibility.

- Components are added via CLI (`npx shadcn-vue@latest add [component]`), copying source files into your codebase for full control and transparency.
- The CLI manages dependencies, theme, and file structure (see `components.json`).
- You are free to edit, extend, or theme components as required—no vendor lock-in.
- All components follow Tailwind v4 and shadcn/ui design patterns for consistency.

For setup and usage, see the official documentation or run `npx shadcn-vue@latest init` in your project root.

---

## Component Standards

### Required Component Structure

```vue
<template>
  <!-- Template with proper accessibility -->
</template>

<script setup lang="ts">
// Imports
import { ref, computed, onMounted } from 'vue'
import type { ComponentProps } from '@/types'

// Props & Emits
interface Props {
  // Define typed props
}
const props = defineProps<Props>()

// Composables
const { data, loading, error } = useApi()

// Local state
const localState = ref('')

// Computed
const computedValue = computed(() => {
  // Estado derivado
})

// Lifecycle
onMounted(() => {
  // Inicialização
})
</script>
```

### Naming Conventions

- **Components**: PascalCase (`JobCard.vue`, `TimesheetEntry.vue`)
- **Composables**: camelCase with `use` prefix (`useJobData`, `useTimesheetValidation`)
- **Stores**: camelCase (`authStore`, `jobStore`)
- **Service files**: camelCase with `.service` suffix (`job.service.ts`)

### File Organization

```
src/
├── components/          # Reusable components
│   ├── ui/             # Base components (Button, Dialog, etc.)
│   ├── job/            # Job-specific components
│   ├── timesheet/      # Timesheet-related components
│   └── kanban/         # Kanban board components
├── composables/        # Composition API functions (20+ composables)
├── stores/             # Pinia stores
├── services/           # API service layer
├── types/              # TypeScript type definitions
├── schemas/            # Zod validation schemas
├── views/              # Page-level components
├── router/             # Vue Router configuration
├── plugins/            # Third-party library configs
├── lib/                # Utility functions
└── assets/             # CSS and static assets
```

## Code Standards

### Composition API

- **ALWAYS** use `<script setup>` syntax
- **ALWAYS** use Composition API, never Options API
- **ALWAYS** type props and emits with TypeScript interfaces
- Use composables for shared logic

### TypeScript

- **ALWAYS** type component props and emits
- Use interfaces for complex objects
- Leverage type inference when possible
- Validate API responses with Zod schemas

### No Fallbacks in Our Own Code

**Do not use fallback patterns when accessing our own API, component data, or environment variables.**

**API/Component Data:**

- ❌ `job.job_number || job.number || job.jobNumber`
- ✅ `job.job_number`

**Environment Variables:**

- ❌ `import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'`
- ✅ `import.meta.env.VITE_API_BASE_URL`

**Config Values:**

- ❌ `config.retryAttempts || 3`
- ✅ `config.retryAttempts`

### State Management

- **Pinia stores** for global state
- **Reactive refs** for local component state
- **Computed properties** for derived state
- **Actions** for async operations

## Validation Standards

### Forms with VeeValidate + Zod

```typescript
import { useForm } from 'vee-validate'
import { toTypedSchema } from '@vee-validate/zod'
import { z } from 'zod'

const schema = z.object({
  name: z.string().min(1, 'Name is required'),
  email: z.string().email('Invalid email'),
})

const { handleSubmit, errors } = useForm({
  validationSchema: toTypedSchema(schema),
})
```

## Styling Standards

### Tailwind CSS v4

- Use Tailwind utility classes
- Follow the project's custom theme
- Implement responsive design
- Use accessibility standards

### UI Components

- Follow shadcn/vue patterns for base components
- Maintain visual consistency
- Implement loading and error states
- Use appropriate animations

#### Using shadcn-vue in Your Project

**shadcn-vue** is an unofficial, community-led Vue port of the popular shadcn/ui library (originally for React). It provides accessible, Tailwind-styled UI component templates that you copy into your project and customize freely. Components are built using Radix Vue primitives for accessibility and flexibility.

**Key points:**

- You copy actual component files into your codebase via a CLI, allowing full control over structure and styling.
- Not a compiled library: you own and can freely edit/extend the components.
- All components follow Tailwind v4 and shadcn/ui design patterns for consistency.

**Quick Start:**

1. Add components with `npx shadcn-vue@latest add [component-name]` (e.g., `alert-dialog`).
2. Import and use the components in the code.

**Example:**

```vue
<script setup lang="ts">
import { AlertDialog, AlertDialogTrigger, AlertDialogContent } from '@/components/ui/alert-dialog'
</script>

<template>
  <AlertDialog>
    <AlertDialogTrigger>Open dialog</AlertDialogTrigger>
    <AlertDialogContent>This is the content</AlertDialogContent>
  </AlertDialog>
</template>
```

## Related References

- See: [06-state-management.md](./06-state-management.md)
- See: [07-component-architecture.md](./07-component-architecture.md)
- See: [05-api-integration.md](./05-api-integration.md)
