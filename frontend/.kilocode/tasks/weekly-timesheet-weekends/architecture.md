# Weekend Timesheets Architecture

## Overview

This document outlines the architectural design for implementing weekend timesheets functionality in the frontend, based on a backend feature flag. The system dynamically adapts between 5-day (Mon-Fri) and 7-day (Mon-Sun) configurations while maintaining backward compatibility and performance.

## System Architecture

### Core Components

#### 1. Feature Flag Service (`src/services/feature-flags.service.ts`)

**Purpose**: Centralized service for detecting weekend timesheets feature flag from environment variables.

**Responsibilities**:

- Read feature flag from environment variable `VITE_WEEKEND_TIMESHEETS_ENABLED`
- Provide simple boolean value based on env var
- Handle invalid values with graceful fallbacks

**Key Methods**:

```typescript
class FeatureFlagsService {
  static isWeekendTimesheetsEnabled(): boolean
  static refreshFlags(): void
}
```

**Environment Variable**:

- `VITE_WEEKEND_TIMESHEETS_ENABLED`: Set to 'true' to enable weekend timesheets, any other value disables it
- Default: false (weekends disabled)

#### 2. Enhanced Timesheet Store (`src/stores/timesheet.ts`)

**Purpose**: Extended Pinia store to manage weekend functionality and dynamic configurations.

**New State Properties**:

```typescript
interface TimesheetStore {
  weekendEnabled: Ref<boolean>
  weekDays: Ref<string[]>
  displayDays: ComputedRef<DayConfig[]>
}
```

**Key Features**:

- Reactive feature flag integration
- Dynamic week configuration (5 or 7 days)
- Computed display days for UI rendering
- Enhanced weekly overview loading

#### 3. Updated Services

**Purpose**: Modified service layer to handle dynamic API responses and feature flag integration.

**Modified Services**:

- `weekly-timesheet.service.ts`: Handle both 5-day and 7-day API responses
- `timesheet.service.ts`: Ensure compatibility with weekend functionality
- `daily-timesheet.service.ts`: Review for any necessary updates

### UI Architecture

#### Component Hierarchy

```
AppLayout
├── WeeklyTimesheetView
│   ├── Header Section
│   │   ├── Title & Date Display
│   │   ├── Action Buttons
│   │   └── Navigation Controls
│   ├── Table Section
│   │   ├── Dynamic Day Headers
│   │   └── Staff Week Rows
│   └── Modals
│       ├── WeeklyMetricsModal
│       └── WeekPickerModal
├── DailyTimesheetView
└── TimesheetEntryView
    ├── Header Section
    ├── AG Grid Component
    └── Bottom Summary Section
```

#### Dynamic UI Components

**Day Headers**: Conditionally render 5 or 7 day columns based on feature flag
**Weekend Styling**: Apply blue background styling to Saturday/Sunday columns when enabled
**Responsive Design**: Maintain mobile and desktop layouts for both configurations

### Data Flow Architecture

#### Feature Flag Detection Flow

```
1. Application Initialization
   ↓
2. FeatureFlagsService.isWeekendTimesheetsEnabled()
   ↓
3. Read Environment Variable: VITE_WEEKEND_TIMESHEETS_ENABLED
   ↓
4. Parse Boolean Value (default: false)
   ↓
5. Update Store: weekendEnabled = result
   ↓
6. Trigger UI Reconfiguration
```

#### Weekly Overview Loading Flow

```
1. User Requests Weekly View
   ↓
2. Check Feature Flag Status
   ↓
3. API Call: GET /api/timesheets/weekly/
   ↓
4. Receive Response (5 or 7 days based on flag)
   ↓
5. Update Store with Dynamic Data
   ↓
6. Render UI with Appropriate Day Count
```

#### Error Handling Flow

```
1. API Call Fails
   ↓
2. Check Error Type
   ↓
3. If Feature Flag Error → Fallback to 5-day mode
   ↓
4. If Data Error → Show user-friendly message
   ↓
5. Log Error for Debugging
   ↓
6. Continue with Degraded Functionality
```

### State Management Architecture

#### Pinia Store Structure

```typescript
// src/stores/timesheet.ts
export const useTimesheetStore = defineStore('timesheet', () => {
  // Existing state
  const staff = ref<Staff[]>([])
  const jobs = ref<Job[]>([])
  const currentWeekData = ref<WeeklyOverviewData | null>(null)

  // New weekend-related state
  const weekendEnabled = ref(false)
  const weekDays = ref<string[]>(['monday', 'tuesday', 'wednesday', 'thursday', 'friday'])

  // Computed properties
  const displayDays = computed(() => {
    if (!currentWeekData.value) return []
    const days = currentWeekData.value.week_days
    if (!weekendEnabled.value) {
      return days.filter((day) => {
        const date = new Date(day)
        const dayOfWeek = date.getDay()
        return dayOfWeek >= 1 && dayOfWeek <= 5 // Mon-Fri
      })
    }
    return days
  })

  // Actions
  function initializeFeatureFlags() {
    weekendEnabled.value = FeatureFlagsService.isWeekendTimesheetsEnabled()
    updateWeekConfiguration()
  }

  function updateWeekConfiguration() {
    if (weekendEnabled.value) {
      weekDays.value = [
        'monday',
        'tuesday',
        'wednesday',
        'thursday',
        'friday',
        'saturday',
        'sunday',
      ]
    } else {
      weekDays.value = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']
    }
  }

  return {
    // ... existing returns
    weekendEnabled: readonly(weekendEnabled),
    weekDays: readonly(weekDays),
    displayDays,
    initializeFeatureFlags,
  }
})
```

### API Integration Architecture

#### Backend API Contracts

**Weekly Timesheet API**:

```typescript
GET /api/timesheets/weekly/
Query Params: { start_date?: string }
Response: {
  start_date: string
  end_date: string
  week_days: string[] // 5 or 7 dates based on feature flag
  staff_data: StaffWeeklyData[]
}
```

### Error Handling Architecture

#### Error Types and Handling

**Data Loading Errors**:

- Weekly overview fails: Show error message, allow retry
- Invalid data format: Log error, show generic message
- Partial data: Use available data, log missing fields

**UI Error Boundaries**:

- Component-level error handling
- Graceful degradation
- User-friendly error messages

### Performance Architecture

#### Caching Strategy

- Weekly data: Store-level caching with invalidation
- API responses: HTTP caching where applicable

#### Optimization Techniques

- Lazy loading of weekend-specific components
- Debounced API calls for user interactions
- Virtual scrolling for large datasets
- Progressive enhancement for feature flag

### Security Architecture

#### Data Protection

- No sensitive data in feature flag responses
- Secure API communication (HTTPS)
- Input validation on all user inputs
- XSS protection through Vue's built-in sanitization

#### Access Control

- Feature flag visibility based on user permissions
- Backend validation of feature flag access
- Audit logging for feature flag changes

### Testing Architecture

#### Unit Testing

- Feature flag service functionality
- Store state management
- Component rendering with different configurations
- API service methods

#### Integration Testing

- End-to-end feature flag detection
- UI adaptation for both configurations
- API integration with mock responses
- Error handling scenarios

#### Performance Testing

- Feature flag detection timing
- UI rendering performance
- API response times
- Memory usage with large datasets

### Deployment Architecture

#### Feature Flag Configuration

- Environment variable: `VITE_WEEKEND_TIMESHEETS_ENABLED=true`
- Build-time configuration (no runtime API calls)
- Easy rollback by changing environment variable
- Version control of feature state

#### Backward Compatibility

- Graceful degradation for older clients
- API versioning support
- Database migration handling
- Configuration persistence

### Monitoring and Observability

#### Metrics to Track

- Feature flag detection success rate
- API response times
- UI rendering performance
- Error rates by component
- User adoption rates

#### Logging Strategy

- Structured logging with correlation IDs
- Error tracking with stack traces
- Performance metrics collection
- User interaction analytics

### Future Extensibility

#### Modular Design

- Plugin architecture for additional features
- Configuration-driven UI components
- Service layer abstraction
- Event-driven architecture

#### Scalability Considerations

- Horizontal scaling support
- CDN integration for static assets
- Database connection pooling
- Caching layer integration

This architecture ensures a robust, scalable, and maintainable implementation of weekend timesheets functionality while preserving backward compatibility and providing excellent user experience.
