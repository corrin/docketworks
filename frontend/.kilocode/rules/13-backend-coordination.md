# Backend-Frontend Coordination

## 🚨 MANDATORY COORDINATION RULES 🚨

### Absolute Prohibition of Backend Access

**This Claude instance is NOT allowed to read or modify the backend directory or source code.**

**ALWAYS coordinate with the backend Claude through the user for:**

### Data Ownership Questions

- "Is this data from the database or a UI constant?"
- "Do these values come from the database or are they UI constants?"
- "Should job status options come from the backend API?" (Answer: No – static constants)
- "Does user profile data need a backend serializer?" (Answer: Yes – dynamic data)

### API Contract Questions

- "Which fields does the [specific] API actually return?"
- "Does [ModelName] have a '[field]' field?"
- "What is the real response structure for this endpoint?"

### Business Logic Questions

- "Is this business logic (backend) or presentation logic (frontend)?"
- "Should the frontend calculate [specific calculation]?"
- "Are there business rules I need to know about this data?"

### Schema Generation Questions

- "Does the frontend need a schema for [specific type] – should this exist?"
- "Does the backend already have a serializer for this data?"

## Coordination Process

### Claude Frontend Workflow

1. **Before assuming data source:** Ask "Is this from the database or a UI constant?"
2. **Before creating types:** Ask "Does the backend already serialize this?"
3. **Before implementing logic:** Ask "Is this business or presentation logic?"
4. **When schemas are missing:** Provide a specific use case, not generic type requests

### Emergency Prevention – MUST coordinate before:

- Creating any schema/type that may represent backend data
- Implementing calculations that may be business logic
- Making assumptions about API response structures
- Hardcoding values that may be dynamic in the backend

## Data Architecture Decision Examples

### Claude Frontend MUST Coordinate:

```typescript
// ❓ COORDINATE – Dynamic model data?
interface UserProfile {
  wage_rate?: number // Changes based on staff record
  permissions: string[] // Based on role, stored in DB
}

// ❓ COORDINATE – Calculated business data?
interface JobSummary {
  profitMargin: number // Business calculation
  totalCost: number // Aggregated from CostLines
}
```

### Claude Frontend SHOULD Handle Locally:

```typescript
// ✅ UI CONSTANTS – Frontend owns these
const JOB_STATUS_CHOICES = [{ key: 'draft', label: 'Draft' }]

// ✅ PRESENTATION LOGIC – Frontend owns these
interface TableColumn {
  field: string
  header: string
  sortable: boolean
}
```

## Backend Architecture (Provided by Backend Claude)

### System Architecture:

- Django REST Framework with MariaDB (MySQL compatible)
- UUID primary keys throughout for security
- Modern CostSet/CostLine architecture (NO legacy JobPricing models)
- SimpleHistory for audit trails on critical models
- drf_spectacular for OpenAPI schema generation
- Defensive programming philosophy – fail early, no fallbacks, mandatory error persistence

### Core Django Apps:

- **workflow** – Core functionality, Xero integration, authentication
- **job** – Job lifecycle with modern costing (CostSet/CostLine)
- **accounts** – Staff management with custom user model
- **client** – Client relationship management
- **timesheet** – Time tracking via CostLine architecture
- **purchasing** – Purchase orders with Xero integration
- **accounting** – Financial reports and KPIs
- **quoting** – Quoting and supplier pricing

## Schema Coordination

### When Generated Schema Is Wrong

Coordinate with backend to add proper `@extend_schema_field` annotations, then regenerate with:

```bash
npm run update-schema
```

### Schema Update Process

1. **Backend available:** Fresh schema is fetched from `http://localhost:8000/api/schema/`
2. **Backend unavailable:** Build continues with existing `schema.yml`
3. **Automatic generation:** `openapi-zod-client` generates TypeScript types
4. **Integration:** Types are available in `@/api/generated/api`

## Communication Standards

### Specific vs Generic Requests

```typescript
// ✅ CORRECT – Specific request with context
"I need a schema for timesheet entry data that includes:
- job_id (job reference)
- staff_id (staff reference)
- date (entry date)
- hours (hours worked)
- description (work description)
- rate (hourly rate)

This is for the TimesheetEntryForm component where users log time spent on jobs."

// ❌ INCORRECT – Generic request
"I need a TimesheetEntry type"
```

### Validation Questions

```typescript
// ✅ CORRECT – Specific business rule question
"Are there validation rules for timesheet entries that the frontend should know?
For example:
- Maximum hours per day?
- Date restrictions (cannot be in the future)?
- Active job validation?"

// ❌ INCORRECT – Assuming validation
// Implementing validation without confirming business rules
```

## Handling Ambiguous Data

### When Unsure About Data Ownership

```typescript
// ❓ COORDINATION NEEDED EXAMPLE
interface JobMetrics {
  // Are these calculated by backend or frontend?
  totalHours: number // ❓ Sum of timesheet entries?
  remainingBudget: number // ❓ Business calculation?
  completionPercentage: number // ❓ Based on what criteria?
}

// ACTION: Coordinate before implementing
// "Are these fields in JobMetrics calculated by backend or frontend?
//  What are the calculation criteria?"
```

### Decision Flow

1. **Identify ambiguous data** – Anything that can be calculated or stored
2. **Formulate a specific question** – Include usage context
3. **Wait for backend response** – Do not assume or implement
4. **Implement based on the answer** – Follow received guidance

## Change Synchronization

### When Backend Changes APIs

1. **Change notification** – Backend informs about API changes
2. **Schema update** – Run `npm run update-schema`
3. **Type check** – Run `npm run type-check`
4. **Fix breakages** – Adjust code as needed
5. **Integration test** – Verify end-to-end functionality

### When Frontend Needs New Endpoints

1. **Specify use case** – Describe required functionality
2. **Define data structure** – What fields are needed
3. **Coordinate with backend** – Request implementation
4. **Wait for implementation** – Do not create workarounds
5. **Integrate when ready** – Use generated schemas

## Integration Debugging

### Common Problems

```typescript
// ❌ PROBLEM: Field does not exist in API response
// SOLUTION: Coordinate with backend to confirm structure

// ❌ PROBLEM: Validation failing
// SOLUTION: Check business rules with backend

// ❌ PROBLEM: Inconsistent calculation
// SOLUTION: Confirm who is responsible for the calculation
```

### Debug Tools

```typescript
// Request logging for debugging
api.interceptors.request.use((config) => {
  if (import.meta.env.DEV) {
    console.log('API Request:', {
      method: config.method,
      url: config.url,
      data: config.data,
    })
  }
  return config
})

api.interceptors.response.use(
  (response) => {
    if (import.meta.env.DEV) {
      console.log('API Response:', {
        url: response.config.url,
        status: response.status,
        data: response.data,
      })
    }
    return response
  },
  (error) => {
    console.error('API Error:', {
      url: error.config?.url,
      status: error.response?.status,
      message: error.response?.data,
    })
    return Promise.reject(error)
  },
)
```

## Full Backend Context

**The backend Claude has full context about database models, API design, and data architecture that the frontend Claude does not have.**

This separation ensures:

- Correct architectural decisions
- Consistency between frontend and backend
- Prevention of logic duplication
- Proper maintenance of separation of concerns

## Related References

- See: [01-architectural-separation.md](./01-architectural-separation.md)
- See: [02-schema-management.md](./02-schema-management.md)
- See: [05-api-integration.md](./05-api-integration.md)
