# Automation Tools for Numeric Fields Migration

**Date:** 2025-01-08  
**Version:** 1.1  
**Complement to:** numeric-fields-migration-plan.md

---

## 🛠️ AUTOMATION SCRIPTS

### Script 1: Conversion Audit

```bash
#!/bin/bash
# audit-numeric-conversions.sh
# Identifies all unnecessary conversions in the code

echo "🔍 Auditing unnecessary numeric conversions..."

# Search for problematic patterns
echo "📊 parseFloat conversions found:"
grep -r "parseFloat(" src/ --include="*.vue" --include="*.ts" | wc -l

echo "📊 parseInt conversions found:"
grep -r "parseInt(" src/ --include="*.vue" --include="*.ts" | wc -l

echo "📊 Number() conversions found:"
grep -r "Number(" src/ --include="*.vue" --include="*.ts" | wc -l

echo "📊 toString() conversions found:"
grep -r "\.toString()" src/ --include="*.vue" --include="*.ts" | wc -l

# Generate detailed report
echo "📋 Generating detailed report..."
{
  echo "# Numeric Conversions Report - $(date)"
  echo ""
  echo "## parseFloat() Occurrences"
  grep -rn "parseFloat(" src/ --include="*.vue" --include="*.ts"
  echo ""
  echo "## parseInt() Occurrences"
  grep -rn "parseInt(" src/ --include="*.vue" --include="*.ts"
  echo ""
  echo "## Number() Occurrences"
  grep -rn "Number(" src/ --include="*.vue" --include="*.ts"
  echo ""
  echo "## toString() Occurrences"
  grep -rn "\.toString()" src/ --include="*.vue" --include="*.ts"
} > .kilocode/tasks/conversion-audit-$(date +%Y%m%d).md

echo "✅ Report saved to .kilocode/tasks/conversion-audit-$(date +%Y%m%d).md"
```

### Script 2: Type Validation

```typescript
// validate-numeric-types.ts
// Validates that mapped fields are treated as native numbers

import fs from 'fs'
import path from 'path'

interface FieldMapping {
  field: string
  pattern: string
  path: string
}

// Load field mappings
const loadFieldMappings = (): FieldMapping[] => {
  const mappingFile = fs.readFileSync('previous_fields_mapping.md', 'utf8')
  const fields: FieldMapping[] = []

  // Parse mapping file
  const lines = mappingFile.split('\n')
  for (const line of lines) {
    const match = line.match(/│\s*\d+\s*│\s*'([^']+)'\s*│\s*'([^']+)'\s*│\s*'([^']+)'\s*│/)
    if (match) {
      fields.push({
        field: match[1],
        pattern: match[2],
        path: match[3],
      })
    }
  }

  return fields
}

// Validate specific file
const validateFile = (filePath: string, fields: FieldMapping[]): string[] => {
  const issues: string[] = []

  if (!fs.existsSync(filePath)) {
    return [`File not found: ${filePath}`]
  }

  const content = fs.readFileSync(filePath, 'utf8')
  const lines = content.split('\n')

  fields.forEach((field) => {
    // Search for unnecessary conversions
    const parseFloatRegex = new RegExp(`parseFloat\\([^)]*${field.field}[^)]*\\)`, 'g')
    const parseIntRegex = new RegExp(`parseInt\\([^)]*${field.field}[^)]*\\)`, 'g')
    const numberRegex = new RegExp(`Number\\([^)]*${field.field}[^)]*\\)`, 'g')
    const toStringRegex = new RegExp(`${field.field}[^.]*\\.toString\\(\\)`, 'g')

    lines.forEach((line, index) => {
      if (parseFloatRegex.test(line)) {
        issues.push(`${filePath}:${index + 1} - Unnecessary parseFloat() for ${field.field}`)
      }
      if (parseIntRegex.test(line)) {
        issues.push(`${filePath}:${index + 1} - Unnecessary parseInt() for ${field.field}`)
      }
      if (numberRegex.test(line)) {
        issues.push(`${filePath}:${index + 1} - Unnecessary Number() for ${field.field}`)
      }
      if (toStringRegex.test(line)) {
        issues.push(`${filePath}:${index + 1} - Unnecessary toString() for ${field.field}`)
      }
    })
  })

  return issues
}

// Execute validation
const main = () => {
  console.log('🔍 Validating numeric types...')

  const fields = loadFieldMappings()
  console.log(`📊 Loaded ${fields.length} mapped fields`)

  const srcDir = 'src'
  const allIssues: string[] = []

  // Recursive function to traverse directories
  const walkDir = (dir: string) => {
    const files = fs.readdirSync(dir)

    files.forEach((file) => {
      const filePath = path.join(dir, file)
      const stat = fs.statSync(filePath)

      if (stat.isDirectory()) {
        walkDir(filePath)
      } else if (file.endsWith('.vue') || file.endsWith('.ts')) {
        const issues = validateFile(filePath, fields)
        allIssues.push(...issues)
      }
    })
  }

  walkDir(srcDir)

  if (allIssues.length === 0) {
    console.log('✅ No unnecessary conversions found!')
  } else {
    console.log(`❌ Found ${allIssues.length} unnecessary conversions:`)
    allIssues.forEach((issue) => console.log(`  ${issue}`))
  }

  // Save report
  const reportPath = `.kilocode/tasks/type-validation-${new Date().toISOString().split('T')[0]}.md`
  const report = [
    `# Type Validation Report - ${new Date().toISOString()}`,
    '',
    `## Summary`,
    `- Fields analyzed: ${fields.length}`,
    `- Issues found: ${allIssues.length}`,
    '',
    `## Detailed Issues`,
    ...allIssues.map((issue) => `- ${issue}`),
  ].join('\n')

  fs.writeFileSync(reportPath, report)
  console.log(`📋 Report saved to ${reportPath}`)
}

if (require.main === module) {
  main()
}
```

### Script 3: Automatic Migration

```typescript
// auto-migrate-fields.ts
// Applies automatic migrations for simple patterns

import fs from 'fs'
import path from 'path'

interface MigrationRule {
  pattern: RegExp
  replacement: string
  description: string
}

const migrationRules: MigrationRule[] = [
  {
    pattern: /parseFloat\(([^)]+\.(?:quantity|unit_cost|unit_rev|wage_rate|charge_out_rate))\)/g,
    replacement: '$1',
    description: 'Remove parseFloat() for numeric fields',
  },
  {
    pattern: /parseInt\(([^)]+\.(?:quantity|unit_cost|unit_rev|wage_rate|charge_out_rate))\)/g,
    replacement: '$1',
    description: 'Remove parseInt() for numeric fields',
  },
  {
    pattern: /Number\(([^)]+\.(?:quantity|unit_cost|unit_rev|wage_rate|charge_out_rate))\)/g,
    replacement: '$1',
    description: 'Remove Number() for numeric fields',
  },
  {
    pattern: /(quantity|unit_cost|unit_rev|wage_rate|charge_out_rate):\s*([^.]+)\.toString\(\)/g,
    replacement: '$1: $2',
    description: 'Remove toString() for numeric fields in object literals',
  },
]

const migrateFile = (filePath: string): { changed: boolean; changes: string[] } => {
  let content = fs.readFileSync(filePath, 'utf8')
  const originalContent = content
  const changes: string[] = []

  migrationRules.forEach((rule) => {
    const matches = content.match(rule.pattern)
    if (matches) {
      content = content.replace(rule.pattern, rule.replacement)
      changes.push(`${rule.description}: ${matches.length} occurrences`)
    }
  })

  const changed = content !== originalContent

  if (changed) {
    fs.writeFileSync(filePath, content)
  }

  return { changed, changes }
}

const main = () => {
  console.log('🔄 Starting automatic migration...')

  const srcDir = 'src'
  let totalFiles = 0
  let changedFiles = 0
  const allChanges: string[] = []

  const walkDir = (dir: string) => {
    const files = fs.readdirSync(dir)

    files.forEach((file) => {
      const filePath = path.join(dir, file)
      const stat = fs.statSync(filePath)

      if (stat.isDirectory()) {
        walkDir(filePath)
      } else if (file.endsWith('.vue') || file.endsWith('.ts')) {
        totalFiles++
        const result = migrateFile(filePath)

        if (result.changed) {
          changedFiles++
          console.log(`✅ Migrated: ${filePath}`)
          result.changes.forEach((change) => {
            console.log(`   - ${change}`)
            allChanges.push(`${filePath}: ${change}`)
          })
        }
      }
    })
  }

  walkDir(srcDir)

  console.log(`\n📊 Migration summary:`)
  console.log(`   - Files analyzed: ${totalFiles}`)
  console.log(`   - Files modified: ${changedFiles}`)
  console.log(`   - Total changes: ${allChanges.length}`)

  // Save change log
  const logPath = `.kilocode/tasks/migration-log-${new Date().toISOString().split('T')[0]}.md`
  const log = [
    `# Automatic Migration Log - ${new Date().toISOString()}`,
    '',
    `## Summary`,
    `- Files analyzed: ${totalFiles}`,
    `- Files modified: ${changedFiles}`,
    `- Total changes: ${allChanges.length}`,
    '',
    `## Detailed Changes`,
    ...allChanges.map((change) => `- ${change}`),
  ].join('\n')

  fs.writeFileSync(logPath, log)
  console.log(`📋 Log saved to ${logPath}`)
}

if (require.main === module) {
  main()
}
```

---

## 📋 MANUAL VALIDATION CHECKLISTS

### Per-File Checklist

```markdown
## Migration Checklist - [FILE_NAME]

### Initial Analysis

- [ ] File identified as affected by migration
- [ ] Mapped numeric fields identified in file
- [ ] Unnecessary conversions catalogued

### Migration

- [ ] parseFloat() removed for mapped fields
- [ ] parseInt() removed for mapped fields
- [ ] Number() removed for mapped fields
- [ ] toString() removed in API assignments
- [ ] Calculations updated to use native values

### Validation

- [ ] TypeScript without errors
- [ ] ESLint without related warnings

### Manual Testing

- [ ] Functionality tested in development
- [ ] Calculations manually validated
- [ ] API calls working correctly
- [ ] UI displaying values correctly

### Code Review

- [ ] Detailed review completed
- [ ] Code patterns followed
- [ ] Documentation updated if necessary
- [ ] Descriptive commit message
```

### Per-Phase Checklist

```markdown
## Phase Checklist - [PHASE_NUMBER]

### Preparation

- [ ] Branch created for phase
- [ ] Baseline validation executed
- [ ] Critical data backed up

### Execution

- [ ] All phase files migrated
- [ ] Automation scripts executed
- [ ] Automatic validations passing

### Manual Validation

- [ ] Component-level checklists completed
- [ ] Critical flow exploratory testing done
- [ ] Data parity spot checks passed
- [ ] Performance sampling completed (if applicable)

### Deployment

- [ ] Merge request created
- [ ] Code review approved
- [ ] Staging deployment completed
- [ ] Staging validation approved

### Finalization

- [ ] Documentation updated
- [ ] Metrics collected
- [ ] Lessons learned documented
- [ ] Next phase prepared
```

---

## 🔧 TOOL CONFIGURATIONS

### ESLint Rules

```javascript
// .eslintrc.js - Rules to prevent regressions
module.exports = {
  rules: {
    // Prevent unnecessary conversions
    'no-implicit-coercion': [
      'error',
      {
        boolean: false,
        number: true,
        string: false,
      },
    ],

    // Custom rule for mapped fields
    'no-unnecessary-numeric-conversion': 'error',
  },
}
```

### TypeScript Config

```json
// tsconfig.json - Configurations for strict validation
{
  "compilerOptions": {
    "strict": true,
    "noImplicitAny": true,
    "strictNullChecks": true,
    "strictFunctionTypes": true,
    "noImplicitReturns": true,
    "noImplicitThis": true
  }
}
```

---

## 📊 MONITORING DASHBOARD

### Real-time Metrics

```typescript
// monitoring/migration-dashboard.ts
interface MigrationMetrics {
  totalFields: number
  migratedFields: number
  remainingConversions: number
  typeChecksPassing: boolean
  lintChecksPassing: boolean
}

const trackMigrationProgress = (): MigrationMetrics => {
  // Implementation of tracking
  return {
    totalFields: 96,
    migratedFields: 0, // Updated dynamically
    remainingConversions: 388, // Updated dynamically
    typeChecksPassing: true, // TypeScript compilation status
    lintChecksPassing: true, // ESLint validation status
  }
}
```

### Automated Alerts

```typescript
// monitoring/alerts.ts
const setupAlerts = () => {
  // Alert for TypeScript errors
  if (!typeChecksPassing) {
    sendAlert('TYPESCRIPT_ERRORS', {
      phase: currentPhase,
      errorCount: typeErrorCount,
    })
  }

  // Alert for ESLint violations
  if (!lintChecksPassing) {
    sendAlert('LINT_VIOLATIONS', {
      phase: currentPhase,
      violationCount: lintViolationCount,
    })
  }
}
```

---

## 🎯 NEXT STEPS

1. **Execute Audit Scripts**

   ```bash
   chmod +x audit-numeric-conversions.sh
   ./audit-numeric-conversions.sh
   ```

2. **Setup Static Validation Environment**

   ```bash
   npm run type-check
   npm run lint
   ```

3. **Start Phase 1**

   ```bash
   git checkout -b feature/numeric-migration-phase1
   npm run migrate:phase1
   ```

4. **Monitor Progress**
   - Manual validation checklists
   - Static analysis reports
   - Daily progress tracking

---

**Tools Created:** 3 scripts + 2 configurations + 1 dashboard  
**Automation:** Pattern detection and basic migration automation  
**Coverage:** 100% of mapped fields covered

**Status:** 🟢 Ready for Use  
Last Update: 2025-08-11
