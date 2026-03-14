# Financial Tabs Migration Plan

## Overview

This plan outlines the migration of financial information from `JobFinancialTab.vue` to `JobActualTab.vue`, including the creation of a centralised composable for financial data management and the relocation of quote functionality to `JobQuoteTab.vue`.

## Requirements

### Functional Requirements

1. **Financial Cards Migration**

   - Move estimate, time & expenses, invoiced, and to be invoiced cards from `JobFinancialTab.vue` to `JobActualTab.vue`
   - Cards should be smaller and positioned in the available space next to Actual Costs
   - Maintain all existing functionality and calculations

2. **Invoices Management**

   - Move invoices list and create invoice button from `JobFinancialTab.vue` to `JobActualTab.vue`
   - Position invoices grid below the Actual Summary section
   - Preserve all Xero integration functionality

3. **Composable Creation**

   - Create `useFinances` composable to centralise financial data management
   - Include quote operations and invoice management
   - Provide reactive state for all financial metrics

4. **Quote Grid Relocation**

   - Move quote grid from `JobFinancialTab.vue` to `JobQuoteTab.vue`
   - Ensure all quote operations remain functional

5. **Print Shortcuts Addition**

   - Add print and download sheet buttons to `JobQuoteTab.vue`
   - Reuse existing print functionality from `JobPdfTab.vue`
   - Maintain consistent UI/UX

6. **Xero Operations Preservation**
   - All quote and invoice Xero operations must remain unchanged
   - Ensure backward compatibility with existing workflows

### Technical Requirements

- Maintain TypeScript type safety throughout
- Preserve all existing API integrations
- Ensure responsive design on all screen sizes
- Follow established architectural patterns
- No breaking changes to existing functionality

## Architecture

### Composable Design (`useFinances`)

```typescript
interface UseFinancesReturn {
  // Financial metrics
  estimateTotal: ComputedRef<number>
  timeAndExpenses: ComputedRef<number>
  invoiceTotal: ComputedRef<number>
  toBeInvoiced: ComputedRef<number>
  quoteTotal: ComputedRef<number>

  // Invoice management
  invoices: Ref<Invoice[]>
  isCreatingInvoice: Ref<boolean>
  deletingInvoiceId: Ref<string | null>

  // Quote operations
  isQuoteDeleted: Ref<boolean>
  isDeletingQuote: Ref<boolean>
  isCreatingQuote: Ref<boolean>
  isAcceptingQuote: Ref<boolean>
  quoteUrl: ComputedRef<string | null>

  // Actions
  createQuote: () => Promise<void>
  acceptQuote: () => Promise<void>
  deleteQuoteOnXero: () => Promise<void>
  goToQuoteOnXero: () => void

  createInvoice: () => Promise<void>
  goToInvoiceOnXero: (url: string) => void
  deleteInvoiceOnXero: (invoiceId: string) => Promise<void>

  // Formatting
  formatCurrency: (amount: number) => string
  formatDate: (date: string) => string
}
```

### Component Structure

#### JobActualTab.vue (After Migration)

```
┌─────────────────────────────────────┐
│ Header: Actual Costs                │
│ [Actual Cost Dropdown]              │
├─────────────────────────────────────┤
│ ┌─────────────┬─────────────────────┐ │
│ │ Cost Lines  │ Financial Cards     │ │
│ │ Grid        │ (Estimate, Time &   │ │
│ │             │ Expenses, Invoiced, │ │
│ │             │ To Be Invoiced)     │ │
│ └─────────────┴─────────────────────┘ │
├─────────────────────────────────────┤
│ Actual Summary                       │
├─────────────────────────────────────┤
│ Invoices Grid                        │
│ [Create Invoice Button]              │
└─────────────────────────────────────┘
```

#### JobQuoteTab.vue (After Migration)

```
┌─────────────────────────────────────┐
│ Header: Quote Management            │
│ [Buttons: Copy from Estimate,       │
│  Quote Revisions, Link Spreadsheet, │
│  Refresh, Print, Download]          │
├─────────────────────────────────────┤
│ Quote Details Grid                  │
├─────────────────────────────────────┤
│ Quote Summary                       │
└─────────────────────────────────────┘
```

## Implementation Tasks

### Phase 1: Composable Creation

1. **Create `useFinances` Composable**

   - Extract financial calculations from `JobFinancialTab.vue`
   - Implement reactive state management
   - Add quote and invoice operations
   - Include proper error handling

2. **Test Composable Integration**
   - Verify all calculations work correctly
   - Test Xero API integrations
   - Ensure proper reactivity

### Phase 2: JobActualTab Migration

3. **Add Financial Cards to JobActualTab**

   - Import and integrate financial cards
   - Position cards in available space
   - Adjust card sizes for compact layout
   - Connect to `useFinances` composable

4. **Add Invoices Section to JobActualTab**

   - Move invoices grid below Actual Summary
   - Integrate create invoice functionality
   - Connect to `useFinances` composable

5. **Update JobActualTab Layout**
   - Adjust grid layout to accommodate new sections
   - Ensure responsive design
   - Test on different screen sizes

### Phase 3: JobQuoteTab Enhancement

6. **Move Quote Grid to JobQuoteTab**

   - Extract quote grid from `JobFinancialTab.vue`
   - Integrate into `JobQuoteTab.vue`
   - Connect to `useFinances` composable

7. **Add Print Shortcuts to JobQuoteTab**
   - Import print/download functionality from `JobPdfTab.vue`
   - Add buttons to header section
   - Ensure proper integration with job data

### Phase 4: Cleanup and Testing

8. **Update JobFinancialTab References**

   - Remove financial cards and invoices from `JobFinancialTab.vue`
   - Keep only quote section temporarily
   - Update any component references

9. **Remove JobFinancialTab Completely**

   - Delete `JobFinancialTab.vue` file
   - Update routing and navigation
   - Clean up any remaining references

10. **Comprehensive Testing**
    - Test all financial calculations
    - Verify Xero integrations work
    - Test print functionality
    - Ensure no regressions

## Dependencies

### External Dependencies

- Xero API integration (must remain functional)
- Vue 3 Composition API
- Existing UI components (Button, Card, Table, etc.)
- Job data structure from API

### Internal Dependencies

- `JobActualTab.vue` current layout
- `JobQuoteTab.vue` current structure
- `JobPdfTab.vue` print functionality
- Existing composables and services

## Risk Assessment

### High Risk

- Xero API integration breakage
- Financial calculation errors
- Loss of existing functionality

### Medium Risk

- Layout and responsive design issues
- Print functionality integration problems
- Component state management conflicts

### Low Risk

- Composable creation and testing
- UI component styling adjustments
- File cleanup and reference updates

## Success Criteria

1. All financial cards display correctly in `JobActualTab.vue`
2. Invoices list and creation work in `JobActualTab.vue`
3. Quote grid functions in `JobQuoteTab.vue`
4. Print shortcuts work in `JobQuoteTab.vue`
5. All Xero operations remain functional
6. No breaking changes to existing workflows
7. Responsive design maintained
8. TypeScript compilation successful
9. All tests pass

## Rollback Plan

If issues arise during implementation:

1. **Composable Issues**: Revert to direct component logic
2. **Layout Problems**: Restore original component structures
3. **Xero Integration**: Verify API endpoints and authentication
4. **Print Functionality**: Use original `JobPdfTab.vue` as fallback

## Timeline

- **Phase 1**: 2-3 days (Composable creation and testing)
- **Phase 2**: 3-4 days (JobActualTab migration)
- **Phase 3**: 2-3 days (JobQuoteTab enhancement)
- **Phase 4**: 1-2 days (Cleanup and testing)

Total estimated time: 8-12 days

## Testing Strategy

### Unit Tests

- Test `useFinances` composable calculations
- Test component integrations
- Test Xero API calls

### Integration Tests

- Test financial data flow between components
- Test print functionality integration
- Test responsive layout

### End-to-End Tests

- Test complete user workflows
- Test Xero integration end-to-end
- Test on different devices and browsers

## Documentation Updates

1. Update component documentation
2. Update API integration docs
3. Add composable usage examples
4. Update testing documentation

## Communication Plan

1. **Team Notification**: Inform team of planned changes
2. **Progress Updates**: Regular status updates during implementation
3. **Testing Coordination**: Coordinate testing with QA team
4. **Deployment Planning**: Plan deployment and monitoring

---

**Document Version**: 1.0
**Date**: September 2025
**Author**: Kilo Code AI
**Status**: Ready for Implementation
