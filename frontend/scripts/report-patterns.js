#!/usr/bin/env node
/**
 * scripts/report-patterns.js
 *
 * Walks through an OpenAPI/YAML file and lists all regex patterns found,
 * also showing the field name (when possible) and the path to it.
 */
import path from 'path'
import SwaggerParser from '@apidevtools/swagger-parser'

/**
 * Recursively walk the object searching for `pattern` keys
 * @param {*} node          current node
 * @param {string[]} trail  list of keys so far (to display the path)
 * @param {Array} out       results accumulator
 * @param {string|null} propName  property name if we are under `properties`
 */
function walk(node, trail = [], out = [], propName = null) {
  if (!node || typeof node !== 'object') return

  // If this object has a pattern, capture it
  if (typeof node.pattern === 'string') {
    out.push({
      field: propName ?? '(unknown)', // can be null in allOf etc.
      pattern: node.pattern,
      path: trail.join('.'),
    })
  }

  // `properties` → we need to know which field (key) it is
  if (node.properties && typeof node.properties === 'object') {
    for (const [k, v] of Object.entries(node.properties)) {
      walk(v, [...trail, 'properties', k], out, k)
    }
  }

  // Recursively walk other relevant keys
  for (const [k, v] of Object.entries(node)) {
    if (['properties', 'pattern'].includes(k)) continue
    if (Array.isArray(v)) v.forEach((item, idx) => walk(item, [...trail, `${k}[${idx}]`], out))
    else if (typeof v === 'object') walk(v, [...trail, k], out)
  }
}

async function main() {
  const specFile = process.argv[2] ?? 'schema.yml'
  const specPath = path.resolve(process.cwd(), specFile)

  const openapi = await SwaggerParser.parse(specPath) // resolve $refs
  const results = []
  walk(openapi, [], results)

  if (!results.length) {
    console.log('No fields with pattern found.')
    return
  }

  // Print results as a table
  console.table(
    results.map((r) => ({
      field: r.field,
      pattern: r.pattern,
      path: r.path,
    })),
  )

  // Additionally, show unique regex patterns
  const uniques = [...new Set(results.map((r) => r.pattern))]
  console.log('\nUnique regex patterns found:\n', uniques.join('\n'))
}

main().catch((err) => {
  console.error('Error while scanning schema:', err)
  process.exit(1)
})
