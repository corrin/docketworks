# Critical Architectural Separation

## 🚨 FUNDAMENTAL RULE: ABSOLUTE FRONTEND-BACKEND SEPARATION 🚨

### Exclusive Frontend Responsibilities

**NEVER put backend logic in the frontend. NEVER put frontend logic in the backend.**

The frontend is ONLY responsible for:

- User interface and presentation logic
- User interactions and form handling
- Client-side validation for UX (NEVER for security)
- Routing and navigation
- **STATIC CONSTANTS AND CONFIGURATION**
- Display formatting and styling

### Absolute Prohibitions

**NEVER request backend schemas for:**

- ❌ Static dropdown choices (status values, categories, etc.)
- ❌ UI constants that never change
- ❌ Configuration data that should be hardcoded in the frontend
- ❌ Enums or choice fields that are purely presentational
- ❌ Display labels, tooltips, or UI text

### Golden Rule

**If it is a constant that never changes and has no business logic, it belongs in YOUR code as a TypeScript constant. DO NOT request it from the backend.**

### Implementation Examples

```typescript
// ✅ CORRECT - Frontend constants
const JOB_STATUS_CHOICES = [
  { key: 'draft', label: 'Draft' },
  { key: 'active', label: 'Active' },
  { key: 'completed', label: 'Completed' },
]

// ❌ INCORRECT - Do not request from backend
// Do not create endpoints for static data
```

### Conformance Validation

Before creating any type or interface, ask:

1. "Is this data stored in the database?"
2. "Does this data change based on business logic?"
3. "Is this data calculated by the backend?"

If the answer is YES to any question, use backend schemas.
If the answer is NO to all, create it as a frontend constant.

### Related References

- See: [02-schema-management.md](./02-schema-management.md)
- See: [13-backend-coordination.md](./13-backend-coordination.md)
