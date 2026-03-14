# Authentication and Security

## Authentication Flow

### Security Architecture

- **httpOnly cookies** for secure token storage
- Automatic token refresh via Axios interceptors
- Router guards protect authenticated routes
- Auth state managed in `stores/auth.ts`
- Automatic logout on 401 responses

### Authentication Flow Implementation

1. User logs in via `/login` route
2. Backend sets httpOnly cookies
3. Axios automatically includes cookies in requests
4. Router guards check auth state before navigation
5. 401 responses trigger automatic logout

### Security Standards

#### Client-Side vs Server-Side Validation

**IMPORTANT**: Client-side validation is ONLY for UX, NEVER for security

```typescript
// ✅ CORRECT - Validation for UX
const schema = z.object({
  email: z.string().email('Email must be valid'),
  password: z.string().min(8, 'Password must be at least 8 characters'),
})

// ❌ INCORRECT - Never trust frontend validation only
// Real security validation MUST happen on the backend
```

#### Token Management

```typescript
// ✅ CORRECT - Use httpOnly cookies
// Cookies are automatically managed by the browser
// Do not store tokens in localStorage or sessionStorage

// ❌ INCORRECT - Insecure storage
// localStorage.setItem('token', token)
// sessionStorage.setItem('token', token)
```

### Router Guards

```typescript
// Example of authentication guard
router.beforeEach((to, from, next) => {
  const authStore = useAuthStore()
  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    next('/login')
  } else {
    next()
  }
})
```

## Axios Configuration

### Security Interceptors

```typescript
// Request interceptor for CSRF
axios.interceptors.request.use((config) => {
  // CSRF token is automatically included via cookies
  return config
})

// Response interceptor for automatic logout
axios.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Automatic logout on 401
      authStore.logout()
      router.push('/login')
    }
    return Promise.reject(error)
  },
)
```

## Authorization Standards

### Permission Checking

```typescript
// ✅ CORRECT - Check permissions based on backend
const canEditJob = computed(() => {
  return authStore.user?.permissions.includes('job.edit')
})

// ❌ INCORRECT - Authorization logic in frontend
// Never implement business authorization logic in the frontend
```

### Route Protection

```typescript
// Route definition with auth meta
const routes = [
  {
    path: '/jobs',
    component: JobsView,
    meta: {
      requiresAuth: true,
      permissions: ['job.view'],
    },
  },
]
```

## Sensitive Data Handling

### Personal Information

- **NEVER** store sensitive data in localStorage
- **NEVER** log sensitive data in production console
- **ALWAYS** mask sensitive data in development logs

### Environment Configuration

```typescript
// ✅ CORRECT - Use environment variables
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL

// ❌ INCORRECT - Hardcoding URLs or keys
// const API_KEY = 'abc123' // Never do this
```

## Security Headers

### CORS Configuration

- Backend must configure CORS properly
- Frontend should not try to bypass CORS policies
- Use credentials: 'include' for httpOnly cookies

```typescript
// Axios config for cookies
axios.defaults.withCredentials = true
```

## Input Validation

### Sanitization

```typescript
// ✅ CORRECT - Validation and sanitization
const sanitizeInput = (input: string) => {
  return input.trim().replace(/[<>]/g, '')
}

// Use trusted libraries for validation
import { z } from 'zod'
const userSchema = z.object({
  name: z.string().min(1).max(100),
  email: z.string().email(),
})
```

## Security Monitoring

### Security Event Logging

```typescript
// Log important events (no sensitive data)
console.log('Login attempt for user:', user.email)
console.log('Permission denied for action:', action)

// ❌ NEVER log passwords or tokens
// console.log('Password:', password) // NEVER
```

### Anomaly Detection

- Monitor for multiple failed login attempts
- Detect suspicious access patterns
- Implement rate limiting on the backend

## Related References

- See: [05-api-integration.md](./05-api-integration.md)
- See: [08-error-handling.md](./08-error-handling.md)
- See: [06-state-management.md](./06-state-management.md)
