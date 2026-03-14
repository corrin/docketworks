# Codebase Overview

This project is a front-end built with **Vue 3** and **TypeScript** using Vite as the bundler. It communicates with the [Jobs Manager backend](https://github.com/corrin/jobs_manager).

## Key Concepts

- **Single-File Components (SFCs)** combine template, script and style in one file.
- **Composition API** is used heavily through composables in `src/composables/`.
- **Pinia** manages application state, including authentication stored in `stores/auth.ts`.
- **Vue Router** handles page navigation and guards protected routes.
- **Axios** is configured in `plugins/axios.ts` for API calls.

## Directory Layout

```
src/
  assets/       - Tailwind CSS and static assets
  components/   - Reusable Vue components
  composables/  - Composition functions like useKanban
  lib/          - Utility helpers
  plugins/      - Plugins such as Axios setup
  router/       - Vue Router configuration
  schemas/      - Zod schemas for API data
  services/     - API service wrappers
  stores/       - Pinia stores (authentication, etc.)
  types/        - TypeScript interfaces
  views/        - Page-level Vue components
```

## Application Flow

`src/main.ts` bootstraps Vue, installs Pinia and the router, and mounts the root component:

```ts
import './assets/main.css'
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './plugins/axios'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
```

### Routing and Guards

Routes are defined in `src/router/index.ts`. Navigation guards ensure users are authenticated before accessing protected pages:

```ts
router.beforeEach(async (to, from, next) => {
  const authStore = useAuthStore()
  if (to.meta.requiresAuth) {
    if (!authStore.isAuthenticated) {
      await authStore.initializeAuth()
      if (!authStore.isAuthenticated) {
        next({ name: 'login', query: { redirect: to.fullPath } })
        return
      }
    }
  }
  if (to.meta.requiresGuest && authStore.isAuthenticated) {
    next({ name: 'dashboard' })
    return
  }
  next()
})
```

### Authentication Store

The Pinia authentication store manages login/logout actions and user state:

```ts
export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  const isAuthenticated = computed(() => !!user.value)
  const fullName = computed(() => {
    if (!user.value) return ''
    return `${user.value.first_name} ${user.value.last_name}`.trim()
  })
  ...
})
```

### Kanban Feature

`useKanban.ts` encapsulates the job board logic, including loading jobs, search filters and drag‑and‑drop support using SortableJS.

### UI Layout

`AppLayout.vue` renders the site header with navigation links and a logout button.

## Learning Path

- Get comfortable with Vue Single‑File Components.
- Explore the Composition API patterns used in composables.
- Review the authentication flow in the Pinia store and Axios plugin.
- Check how SortableJS is integrated for drag‑and‑drop in the Kanban board.

With these pieces in mind, you can extend the application, add features or debug existing ones.
