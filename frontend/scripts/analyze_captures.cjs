#!/usr/bin/env node
const fs = require('fs')
const path = require('path')

// Find the most recent capture files
const findLatestCaptures = () => {
  // Find project root by looking for package.json
  let projectRoot = __dirname
  while (
    !fs.existsSync(path.join(projectRoot, 'package.json')) &&
    projectRoot !== path.dirname(projectRoot)
  ) {
    projectRoot = path.dirname(projectRoot)
  }
  const outputDir = path.join(projectRoot, 'script-output')
  if (!fs.existsSync(outputDir)) {
    console.error('No script-output directory found. Run capture_metrics.cjs first.')
    process.exit(1)
  }
  const files = fs.readdirSync(outputDir)
  const uatFiles = files
    .filter((f) => f.startsWith('capture_uat_'))
    .sort()
    .reverse()
  const prodFiles = files
    .filter((f) => f.startsWith('capture_production_'))
    .sort()
    .reverse()

  if (!uatFiles.length || !prodFiles.length) {
    console.error(
      'Missing capture files. Run capture_metrics.cjs for both UAT and production first.',
    )
    process.exit(1)
  }

  return {
    uat: uatFiles[0],
    production: prodFiles[0],
  }
}

// Main analysis
const analyze = () => {
  const files = findLatestCaptures()
  console.log(`Comparing:\n  UAT: ${files.uat}\n  PROD: ${files.production}\n`)

  // Find project root by looking for package.json
  let projectRoot = __dirname
  while (
    !fs.existsSync(path.join(projectRoot, 'package.json')) &&
    projectRoot !== path.dirname(projectRoot)
  ) {
    projectRoot = path.dirname(projectRoot)
  }
  const outputDir = path.join(projectRoot, 'script-output')
  const uat = JSON.parse(fs.readFileSync(path.join(outputDir, files.uat), 'utf8'))
  const prod = JSON.parse(fs.readFileSync(path.join(outputDir, files.production), 'utf8'))

  console.log('='.repeat(70))
  console.log('PERFORMANCE COMPARISON')
  console.log('='.repeat(70))

  // 1. Overall timing
  console.log('\n1. OVERALL TIMING')
  console.log('-'.repeat(40))
  console.log(`UAT Total Time: ${uat.totalTime}ms`)
  console.log(`Production Total Time: ${prod.totalTime}ms`)
  console.log(`Difference: ${prod.totalTime - uat.totalTime}ms slower in production`)

  // Protocol summary
  console.log('\nPROTOCOLS')
  console.log('-'.repeat(40))
  const summarizeProtocols = (label, obj) => {
    const nav =
      (obj.protocols && obj.protocols.navigation) ||
      obj.finalState?.performance?.nextHopProtocol ||
      'unknown'
    const res = (obj.protocols && obj.protocols.resources) || {}
    const pairs = Object.entries(res)
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `${k}:${v}`)
      .join(', ')
    console.log(`${label} navigation: ${nav}`)
    console.log(`${label} resources: ${pairs || 'n/a'}`)
  }
  summarizeProtocols('UAT', uat)
  summarizeProtocols('PROD', prod)

  // 2. Navigation timeline
  console.log('\n2. NAVIGATION TIMELINE')
  console.log('-'.repeat(40))

  const getNavigations = (data) => {
    return data.events
      .filter((e) => e.type === 'navigation')
      .map((e) => ({ url: e.url, elapsed: e.elapsed }))
  }

  console.log('\nUAT Navigation:')
  getNavigations(uat).forEach((nav) => {
    console.log(`  ${nav.elapsed}ms: ${nav.url.replace(uat.baseUrl, '[UAT]')}`)
  })

  console.log('\nProduction Navigation:')
  getNavigations(prod).forEach((nav) => {
    console.log(`  ${nav.elapsed}ms: ${nav.url.replace(prod.baseUrl, '[PROD]')}`)
  })

  // 3. Login comparison
  console.log('\n3. LOGIN PROCESS')
  console.log('-'.repeat(40))

  const uatLogin = uat.events.find(
    (e) => e.type === 'timing' && e.message.includes('Login completed'),
  )
  const prodLogin = prod.events.find(
    (e) => e.type === 'timing' && e.message.includes('Login completed'),
  )

  console.log(`UAT Login: ${uatLogin ? uatLogin.message : 'COMPLETED'}`)
  console.log(`UAT After Login URL: ${uat.afterLoginUrl}`)
  console.log(`Production Login: ${prodLogin ? prodLogin.message : 'FAILED/TIMED OUT'}`)
  console.log(`Production After Login URL: ${prod.afterLoginUrl || 'N/A'}`)

  // 4. Final state
  console.log('\n4. FINAL STATE')
  console.log('-'.repeat(40))
  console.log(`UAT Final URL: ${uat.finalState?.url || 'N/A'}`)
  console.log(`UAT Data Rows: ${uat.finalState?.dataRows || 0}`)
  console.log(`UAT Tables: ${uat.finalState?.tables || 0}`)
  console.log(`UAT Body text length: ${uat.finalState?.bodyLength || 0} characters`)
  console.log(`Production Final URL: ${prod.finalState?.url || 'N/A'}`)
  console.log(`Production Data Rows: ${prod.finalState?.dataRows || 0}`)
  console.log(`Production Tables: ${prod.finalState?.tables || 0}`)
  console.log(`Production Body text length: ${prod.finalState?.bodyLength || 0} characters`)

  // 5. Network summary
  console.log('\n5. NETWORK REQUESTS')
  console.log('-'.repeat(40))
  console.log(`UAT Total Requests: ${uat.requests.length}`)
  console.log(`Production Total Requests: ${prod.requests.length}`)

  // Errors
  console.log('\n6. ERRORS')
  console.log('-'.repeat(40))
  console.log(`UAT Errors: ${uat.errors.length}`)
  console.log(`Production Errors: ${prod.errors.length}`)

  if (prod.errors.length > 0) {
    console.log('\nProduction Errors:')
    prod.errors.forEach((e) => console.log(`  - ${e.message || e}`))
  }

  // Key differences snapshot
  console.log('\n' + '='.repeat(70))
  console.log('KEY DIFFERENCES')
  console.log('='.repeat(70))
  const uatKanban = uat.events.find((e) => e.url && e.url.includes('kanban'))
  const prodKanban = prod.events.find((e) => e.url && e.url.includes('kanban'))
  console.log(`UAT navigates to kanban: ${uatKanban ? 'YES' : 'NO'}`)
  console.log(`Production navigates to kanban: ${prodKanban ? 'YES' : 'NO'}`)
}

analyze()
