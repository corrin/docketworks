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
} > .kilocode/tasks/numeric-migration/conversion-audit-$(date +%Y%m%d).md

echo "✅ Report saved to .kilocode/tasks/numeric-migration/conversion-audit-$(date +%Y%m%d).md"