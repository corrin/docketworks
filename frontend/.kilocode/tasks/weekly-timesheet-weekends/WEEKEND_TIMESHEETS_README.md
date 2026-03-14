# Weekend Timesheets Feature

## Overview

The weekend timesheets feature allows the application to display either 5-day (Mon-Fri) or 7-day (Mon-Sun) weekly views based on a feature flag configuration. This provides flexibility for organizations that need to track weekend work.

## Configuration

### Environment Variable

Set the following environment variable to enable weekend timesheets:

```bash
VITE_WEEKEND_TIMESHEETS_ENABLED=true
```

**Supported values:**

- `true`, `1`, `yes`, `on` - Enable weekend timesheets (7-day view)
- `false`, `0`, `no`, `off` - Disable weekend timesheets (5-day view)
- Not set or any other value - Disable weekend timesheets (5-day view)

### Default Behavior

- **Disabled (default)**: Shows Monday-Friday (5 days)
- **Enabled**: Shows Monday-Sunday (7 days)

## Features

### 1. Dynamic Day Headers

- Weekend days (Saturday/Sunday) are visually distinguished with blue styling
- Headers show day names and dates
- Responsive design works on mobile and desktop

### 2. Navigation

- Date navigation respects the weekend feature flag
- "Go to Today" button skips weekends when feature is disabled
- Week navigation works with both 5-day and 7-day configurations

### 3. Visual Indicators

- Weekend days have distinct styling (blue background)
- Status messages indicate feature state

## Implementation Details

### Files Modified

#### Core Services

- `src/services/feature-flags.service.ts` - Feature flag detection with caching
- `src/services/weekly-timesheet.service.ts` - API service layer (no changes needed)
- `src/services/timesheet.service.ts` - Compatibility layer (no changes needed)
- `src/services/daily-timesheet.service.ts` - Daily view service (no changes needed)

#### Store Layer

- `src/stores/timesheet.ts` - Weekend functionality and state management

#### View Components

- `src/views/WeeklyTimesheetView.vue` - Main weekly view with dynamic headers
- `src/views/TimesheetEntryView.vue` - Individual entry view with weekend-aware navigation

#### Type Definitions

- `env.d.ts` - Environment variable types

### Architecture

```
FeatureFlagsService (caching, environment reading)
    ↓
TimesheetStore (state management, weekend logic)
    ↓
WeeklyTimesheetView (UI rendering, dynamic headers)
    ↓
Backend API (returns appropriate day count based on feature flag)
```

## Testing

### Manual Testing

1. **Environment Setup**

   ```bash
   # Enable weekend timesheets
   export VITE_WEEKEND_TIMESHEETS_ENABLED=true

   # Or disable (default)
   export VITE_WEEKEND_TIMESHEETS_ENABLED=false
   ```

2. **Browser Testing**

   - Open the weekly timesheet view
   - Verify day count (5 or 7 days based on setting)
   - Check weekend styling (blue background for Sat/Sun)
   - Test date navigation

3. **Console Validation**
   ```javascript
   // Run validation script
   validateWeekendFeature()
   ```

### Automated Testing

Run the validation script:

```bash
# In browser console
validateWeekendFeature()
```

This will test:

- Feature flag service functionality
- Store initialization
- Weekend detection consistency
- Day configuration accuracy

## Performance Considerations

### Caching

- Feature flag values are cached for 5 minutes
- Reduces environment variable access overhead
- Cache can be manually cleared for testing

### Optimizations

- Lazy loading of weekend-specific UI elements
- Efficient computed properties for day calculations
- Error boundaries prevent crashes on invalid data

## Error Handling

### Graceful Degradation

- If feature flag service fails, defaults to 5-day view
- Invalid API responses show user-friendly error messages
- Navigation continues to work regardless of feature state

### Fallbacks

- Empty state shown when data loading fails
- Default 5-day configuration when feature flag is unavailable
- Console warnings for debugging without breaking UI

## Deployment

### Environment Configuration

**Development:**

```bash
VITE_WEEKEND_TIMESHEETS_ENABLED=true
```

**Production:**

```bash
# Enable for organizations that need weekend tracking
VITE_WEEKEND_TIMESHEETS_ENABLED=true

# Or disable for standard Monday-Friday operations
VITE_WEEKEND_TIMESHEETS_ENABLED=false
```

### Rollback

To disable the feature:

```bash
VITE_WEEKEND_TIMESHEETS_ENABLED=false
```

The application will automatically switch to 5-day mode without requiring a restart.

## Troubleshooting

### Common Issues

1. **Feature not working**

   - Check environment variable is set correctly
   - Verify application restart after environment change
   - Check browser console for errors

2. **Wrong day count**

   - Verify feature flag value
   - Check cache status: `FeatureFlagsService.getCacheStatus()`
   - Clear cache if needed: `FeatureFlagsService.clearCache()`

3. **Styling issues**
   - Ensure CSS classes are loaded
   - Check responsive breakpoints
   - Verify weekend styling is applied correctly

### Debug Commands

```javascript
// Check feature flag status
FeatureFlagsService.getCacheStatus()

// Clear cache and re-read environment
FeatureFlagsService.refreshFlags()

// Run full validation
validateWeekendFeature()

// Check store state
const store = useTimesheetStore()
console.log('Weekend enabled:', store.weekendEnabled)
console.log('Week days:', store.weekDays)
```

## Future Enhancements

### Potential Features

- Per-user weekend preferences
- Custom weekend day configuration
- Weekend-specific reporting
- Time-off tracking for weekends

### API Extensions

- Weekend-specific validation rules
- Bulk weekend time entry
- Weekend overtime calculations

## Support

For issues or questions about the weekend timesheets feature:

1. Check this documentation
2. Run the validation script
3. Check browser console for errors
4. Verify environment configuration
5. Contact development team with debug information

---

**Version:** 1.0.0
**Last Updated:** September 2025
**Compatible with:** Jobs Manager Frontend v2.x
