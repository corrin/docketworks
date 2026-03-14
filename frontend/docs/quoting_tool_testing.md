# Quoting Tool Testing Strategy

## Testing Philosophy

The quoting tool requires rigorous testing because:

- **Financial accuracy** - Wrong calculations cost money
- **Complex business logic** - Multiple calculation methods must agree
- **MCP integration** - External data sources need mocking
- **Estimator workflow** - UX must be tested end-to-end

## Test Structure

### 1. Unit Tests (Phase 1 - Foundation)

#### Material Calculation Logic

```typescript
// tests/unit/useMaterialCalculation.test.ts
describe('Material Calculation', () => {
  describe('calculateAreaWithWaste', () => {
    it('calculates simple box area correctly', () => {
      const spec = {
        type: 'sheet',
        dimensions: { length: 700, width: 700, height: 400 },
        quantity: 3,
      }
      const result = calculateAreaWithWaste(spec, 12)
      expect(result).toBe(4.71) // 1.4 * 1.12 * 3
    })
  })

  describe('calculateTenthsUsage', () => {
    it('counts tenths for standard sheet layout', () => {
      const spec = {
        /* 700x700 part */
      }
      const result = calculateTenthsUsage(spec)
      expect(result).toBe(18) // 6 tenths × 3 parts
    })
  })

  describe('proportional billing vs tenths', () => {
    it('flags large discrepancies between methods', () => {
      const usage = calculateAllMethods(testSpec)
      const variance = Math.abs(usage.tenthsUsed - usage.proportionalBilling)
      expect(variance).toBeLessThan(0.5) // Methods should agree within 0.5 sheets
    })
  })
})
```

#### Input Parsing

```typescript
// tests/unit/inputParser.test.ts
describe('Input Parser', () => {
  it('parses welded box description', () => {
    const input = '3 boxes, 700×700×400, brushed stainless. Welded seams, open top.'
    const result = parseEstimatorInput(input)

    expect(result.quantity).toBe(3)
    expect(result.material).toBe('304/4')
    expect(result.fabricationMethod).toBe('welding')
  })

  it('normalizes material shorthand', () => {
    expect(normalizeMaterial('brushed')).toBe('304/4')
    expect(normalizeMaterial('mild steel')).toBe('mild-steel')
  })

  it('flags ambiguous inputs', () => {
    const input = 'some boxes, stainless steel'
    const validation = validateInput(parseEstimatorInput(input))

    expect(validation.isValid).toBe(false)
    expect(validation.missingFields).toContain('quantity')
    expect(validation.missingFields).toContain('dimensions')
  })
})
```

### 2. Integration Tests (Phase 2 - MCP Integration)

#### MCP Service Mocking

```typescript
// tests/integration/mcpService.test.ts
import { setupMCPMock } from '../mocks/mcpMock'

describe('MCP Integration', () => {
  beforeEach(() => {
    setupMCPMock({
      supplierPrices: [
        { supplier: 'Rivtec', price: 198, partNumber: 'RVT-SS30412' },
        { supplier: 'EDL', price: 236, partNumber: 'EDL-S30412' },
      ],
      remnantStock: null,
    })
  })

  it('fetches supplier prices via MCP', async () => {
    const prices = await QuotingToolService.getInstance().fetchSupplierPrices(materialSpec)

    expect(prices).toHaveLength(2)
    expect(prices[0].supplier).toBe('Rivtec')
    expect(prices[0].unitPrice).toBe(198)
  })

  it('flags large price gaps', async () => {
    setupMCPMock({
      supplierPrices: [
        { supplier: 'A', price: 100 },
        { supplier: 'B', price: 200 }, // 100% gap
      ],
    })

    const prices = await fetchSupplierPrices(materialSpec)
    expect(prices.warnings).toContain('Large price gap detected')
  })
})
```

### 3. End-to-End Tests (Phase 3 - Complete Workflow)

#### Full Quote Generation

```typescript
// tests/e2e/quoteGeneration.test.ts
describe('Complete Quote Generation', () => {
  it('generates accurate quote for welded box example', async () => {
    // Use exact example from documentation
    const input = '3 boxes, 700×700×400, brushed stainless. Welded seams, open top.'

    const quote = await generateCompleteQuote(input)

    // Verify material usage
    expect(quote.materialUsage.totalSheets).toBe(2) // Rounded up from 1.8
    expect(quote.materialUsage.areaWithWaste).toBeCloseTo(4.71)

    // Verify pricing
    expect(quote.lineItems[0].description).toContain('Sheet metal')
    expect(quote.lineItems[0].totalPrice).toBe(396) // 2 × $198

    // Verify labor
    const laborItem = quote.lineItems.find((item) => item.type === 'labor')
    expect(laborItem.totalPrice).toBeCloseTo(327.75) // 3.45 hrs × $95

    // Verify total
    expect(quote.totalQuote).toBeCloseTo(868.5) // With 20% markup
  })

  it('handles quote checking mode', async () => {
    const originalInput = '3 boxes, 700×700×400, brushed stainless'
    const manualQuote = {
      /* manual quote data */
    }

    const comparison = await compareQuotes(originalInput, manualQuote)

    expect(comparison.discrepancies).toHaveLength(0) // Should match
  })
})
```

### 4. Component Tests (Phase 4 - UI Testing)

#### Vue Component Testing

```typescript
// tests/components/EstimatorInput.test.ts
import { mount } from '@vue/test-utils'
import EstimatorInput from '@/components/quoting-tool/EstimatorInput.vue'

describe('EstimatorInput Component', () => {
  it('validates input before proceeding', async () => {
    const wrapper = mount(EstimatorInput)

    await wrapper.find('textarea').setValue('incomplete input')
    await wrapper.find('button[type="submit"]').trigger('click')

    expect(wrapper.emitted('validation-failed')).toBeTruthy()
    expect(wrapper.emitted('input-confirmed')).toBeFalsy()
  })

  it('shows confirmation dialog with parsed data', async () => {
    const wrapper = mount(EstimatorInput)

    await wrapper.find('textarea').setValue('3 boxes, 700×700×400, 304/4')
    await wrapper.find('button[type="submit"]').trigger('click')

    expect(wrapper.find('.confirmation-dialog').exists()).toBe(true)
    expect(wrapper.text()).toContain('3 × box')
    expect(wrapper.text()).toContain('700×700×400')
  })
})
```

## Test Data Management

### Golden Test Cases

Create standardized test cases based on real jobs:

```typescript
// tests/fixtures/goldenTestCases.ts
export const GOLDEN_CASES = [
  {
    name: 'Welded Stainless Box',
    input: '3 boxes, 700×700×400, brushed stainless. Welded seams, open top.',
    expectedOutput: {
      materialUsage: {
        areaWithWaste: 4.71,
        tenthsUsed: 1.8,
        proportionalBilling: 0.873,
        totalSheets: 2,
      },
      totalQuote: 868.5,
    },
  },
  {
    name: 'Mild Steel Plate',
    input: '10 plates, 500×300×3mm, mild steel',
    expectedOutput: {
      /* ... */
    },
  },
]
```

### MCP Mock Data

```typescript
// tests/mocks/mcpMock.ts
export const setupMCPMock = (config: MCPMockConfig) => {
  // Mock MCP server responses
  vi.mock('@/services/mcp', () => ({
    fetchSupplierPrices: vi.fn().mockResolvedValue(config.supplierPrices),
    checkRemnantStock: vi.fn().mockResolvedValue(config.remnantStock),
    calculateLabor: vi.fn().mockResolvedValue(config.laborRates),
  }))
}
```

## Test Automation Strategy

### CI/CD Pipeline

```yaml
# .github/workflows/quoting-tool-tests.yml
name: Quoting Tool Tests
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '18'

      - name: Install dependencies
        run: npm ci

      - name: Run unit tests
        run: npm run test:unit -- --coverage

      - name: Run integration tests
        run: npm run test:integration

      - name: Run E2E tests
        run: npm run test:e2e

      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

### Test Scripts

```json
// package.json
{
  "scripts": {
    "test:unit": "vitest run src/**/*.test.ts",
    "test:integration": "vitest run tests/integration/**/*.test.ts",
    "test:e2e": "vitest run tests/e2e/**/*.test.ts",
    "test:golden": "vitest run tests/golden/**/*.test.ts",
    "test:watch": "vitest watch",
    "test:coverage": "vitest run --coverage"
  }
}
```

## Development Testing Workflow

### 1. TDD for New Features

```typescript
// 1. Write failing test first
describe('new calculation method', () => {
  it('calculates tube bending allowance', () => {
    const result = calculateTubeBending(spec)
    expect(result.bendAllowance).toBe(expectedValue)
  })
})

// 2. Implement minimum code to pass
// 3. Refactor while keeping tests green
```

### 2. Regression Testing

- Golden test cases run on every commit
- Any change to calculation logic requires approval
- Version control for test data and expected outputs

### 3. Manual Testing Checklist

```markdown
## Pre-Release Testing Checklist

### Basic Functionality

- [ ] Can parse simple job descriptions
- [ ] Material calculations agree across all 3 methods
- [ ] Supplier pricing displays correctly
- [ ] Quote totals are mathematically correct

### Edge Cases

- [ ] Handles missing dimensions gracefully
- [ ] Validates material specifications
- [ ] Reports MCP service failures clearly
- [ ] Large quantities don't break calculations

### Integration

- [ ] MCP queries return real data
- [ ] Quote export works in target format
- [ ] Performance acceptable with complex jobs
```

## Performance Testing

### Load Testing

```typescript
// tests/performance/loadTest.ts
describe('Performance Tests', () => {
  it('handles complex multi-part jobs within 2 seconds', async () => {
    const complexJob = generateComplexJob(50) // 50 different parts

    const startTime = Date.now()
    const result = await generateCompleteQuote(complexJob)
    const duration = Date.now() - startTime

    expect(duration).toBeLessThan(2000) // Must complete within 2 seconds
    expect(result.lineItems).toHaveLength(50)
  })
})
```

This testing strategy ensures the quoting tool is reliable, accurate, and maintainable while providing confidence for financial calculations.
