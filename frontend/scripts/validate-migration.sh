#!/bin/bash
# validate-migration.sh
# Validates the migration by running TypeScript checks and ESLint

echo "🔍 Validating numeric migration..."

# TypeScript validation
echo "📝 Running TypeScript validation..."
if npm run type-check; then
    echo "✅ TypeScript validation passed"
else
    echo "❌ TypeScript validation failed"
    exit 1
fi

# ESLint validation
echo "🔧 Running ESLint validation..."
if npm run lint; then
    echo "✅ ESLint validation passed"
else
    echo "❌ ESLint validation failed"
    exit 1
fi

# Check for remaining problematic patterns
echo "🔍 Checking for remaining conversion patterns..."

PARSEFLOAT_COUNT=$(grep -r "parseFloat(" src/ --include="*.vue" --include="*.ts" | wc -l)
PARSEINT_COUNT=$(grep -r "parseInt(" src/ --include="*.vue" --include="*.ts" | wc -l)
NUMBER_COUNT=$(grep -r "Number(" src/ --include="*.vue" --include="*.ts" | wc -l)
TOSTRING_COUNT=$(grep -r "\.toString()" src/ --include="*.vue" --include="*.ts" | wc -l)

echo "📊 Remaining conversions:"
echo "  parseFloat(): $PARSEFLOAT_COUNT"
echo "  parseInt(): $PARSEINT_COUNT"
echo "  Number(): $NUMBER_COUNT"
echo "  toString(): $TOSTRING_COUNT"

# Generate validation report
{
  echo "# Migration Validation Report - $(date)"
  echo ""
  echo "## TypeScript Check: ✅ PASSED"
  echo "## ESLint Check: ✅ PASSED"
  echo ""
  echo "## Remaining Conversions"
  echo "- parseFloat(): $PARSEFLOAT_COUNT"
  echo "- parseInt(): $PARSEINT_COUNT"
  echo "- Number(): $NUMBER_COUNT"
  echo "- toString(): $TOSTRING_COUNT"
  echo ""
  echo "## Files with remaining conversions:"
  if (( PARSEFLOAT_COUNT > 0 || PARSEINT_COUNT > 0 || NUMBER_COUNT > 0 || TOSTRING_COUNT > 0 )); then
    grep -rn "parseFloat(\|parseInt(\|Number(\|\.toString()" src/ --include="*.vue" --include="*.ts"
  else
    echo "No remaining conversions found! 🎉"
  fi
} > ".kilocode/tasks/numeric-migration/validation-report-$(date +%Y%m%d).md"

echo "✅ Validation complete. Report saved to .kilocode/tasks/numeric-migration/validation-report-$(date +%Y%m%d).md"
