const puppeteer = require('puppeteer')
const fs = require('fs')
const path = require('path')

// Load environment variables from frontend root directory
const loadEnv = (env) => {
  // Look for env file in the frontend root directory
  const frontendDir = path.join(__dirname, '..')
  const envFile = path.join(frontendDir, `.env.${env}`)
  if (fs.existsSync(envFile)) {
    const envContent = fs.readFileSync(envFile, 'utf8')
    envContent.split('\n').forEach((line) => {
      const [key, value] = line.split('=')
      if (key && value) {
        process.env[key.trim()] = value.trim()
      }
    })
  } else {
    console.warn(`Warning: Could not find ${envFile}`)
  }
}

const captureMetrics = async (env, jobId) => {
  loadEnv(env)

  const urls = {
    production: 'https://office.morrissheetmetal.co.nz',
    uat: 'https://uat-office.morrissheetmetal.co.nz',
  }

  const baseUrl = urls[env]
  const jobUrl = `${baseUrl}/jobs/${jobId}`

  const results = {
    environment: env,
    timestamp: new Date().toISOString(),
    baseUrl: baseUrl,
    targetUrl: jobUrl,
    events: [],
    requests: [],
    responses: [],
    console: [],
    errors: [],
    metrics: {},
  }

  const log = (type, message, data = {}) => {
    const event = {
      timestamp: Date.now(),
      type,
      message,
      ...data,
    }
    results.events.push(event)
    console.log(`[${type}] ${message}`)
  }

  const browser = await puppeteer.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  })

  const page = await browser.newPage()
  const startTime = Date.now()

  // CDP Network instrumentation to detect pending requests
  const client = await page.target().createCDPSession()
  await client.send('Network.enable')
  const inflight = new Map()
  client.on('Network.requestWillBeSent', (e) => {
    try {
      inflight.set(e.requestId, {
        id: e.requestId,
        url: e.request && e.request.url,
        method: e.request && e.request.method,
        type: e.type,
        ts: Date.now() - startTime,
      })
    } catch {}
  })
  client.on('Network.responseReceived', (e) => {
    const it = inflight.get(e.requestId)
    if (it) {
      it.status = e.response && e.response.status
      it.protocol = e.response && e.response.protocol
      it.mimeType = e.response && e.response.mimeType
    }
  })
  client.on('Network.loadingFinished', (e) => {
    const it = inflight.get(e.requestId)
    if (it) {
      it.finished = true
      it.endTs = Date.now() - startTime
    }
  })
  client.on('Network.loadingFailed', (e) => {
    const it = inflight.get(e.requestId)
    if (it) {
      it.failed = true
      it.errorText = e.errorText
    }
  })

  // Capture all console messages
  page.on('console', (msg) => {
    results.console.push({
      timestamp: Date.now() - startTime,
      type: msg.type(),
      text: msg.text(),
    })
  })

  // Capture all errors
  page.on('error', (err) => {
    results.errors.push({
      timestamp: Date.now() - startTime,
      message: err.message,
    })
  })

  page.on('pageerror', (err) => {
    results.errors.push({
      timestamp: Date.now() - startTime,
      type: 'pageerror',
      message: err.toString(),
    })
  })

  // Capture all requests
  page.on('request', (request) => {
    results.requests.push({
      timestamp: Date.now() - startTime,
      url: request.url(),
      method: request.method(),
      resourceType: request.resourceType(),
    })
  })

  // Capture all responses
  page.on('response', (response) => {
    results.responses.push({
      timestamp: Date.now() - startTime,
      url: response.url(),
      status: response.status(),
      statusText: response.statusText(),
    })
  })

  // Capture navigation events
  page.on('framenavigated', (frame) => {
    if (frame === page.mainFrame()) {
      log('navigation', `Navigated to: ${frame.url()}`, {
        url: frame.url(),
        elapsed: Date.now() - startTime,
      })
    }
  })

  try {
    // STEP 1: Navigate to login
    log('step', 'Navigating to login page')
    await page.goto(`${baseUrl}/login`, {
      waitUntil: 'networkidle2',
      timeout: 30000,
    })

    // Capture login page state
    const loginPageState = await page.evaluate(() => {
      return {
        url: window.location.href,
        title: document.title,
        inputs: Array.from(document.querySelectorAll('input')).map((i) => ({
          type: i.type,
          name: i.name,
          id: i.id,
        })),
      }
    })
    results.loginPageState = loginPageState
    log('capture', 'Login page state captured', loginPageState)

    // STEP 2: Perform login
    log('step', 'Entering credentials')
    const usernameSelector = 'input[name="username"], input[type="text"]:not([type="hidden"])'
    const passwordSelector = 'input[type="password"]'
    const submitSelector = 'button[type="submit"], input[type="submit"]'

    await page.type(usernameSelector, process.env.DJANGO_USER)
    await page.type(passwordSelector, process.env.DJANGO_PASSWORD)

    log('step', 'Submitting login form')
    const loginStart = Date.now()

    const navigationPromise = page.waitForNavigation({
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    })

    await page.click(submitSelector)

    try {
      await navigationPromise
      const loginTime = Date.now() - loginStart
      log('timing', `Login completed in ${loginTime}ms`)

      const afterLoginUrl = page.url()
      results.afterLoginUrl = afterLoginUrl
      log('capture', `After login URL: ${afterLoginUrl}`)
    } catch (navError) {
      log('error', `Login navigation error: ${navError.message}`)
    }

    await new Promise((resolve) => setTimeout(resolve, 2000))

    // STEP 3: Navigate to job page
    log('step', 'Navigating to job page')
    const jobLoadStart = Date.now()

    try {
      await page.goto(jobUrl, {
        waitUntil: 'networkidle2',
        timeout: 600000,
      })

      const jobLoadTime = Date.now() - jobLoadStart
      log('timing', `Job page loaded in ${jobLoadTime}ms`)
    } catch (loadError) {
      log('error', `Job page load error: ${loadError.message}`)
    }

    // STEP 4: Capture final state
    const finalState = await page.evaluate(() => {
      const perf = performance.getEntriesByType('navigation')[0]
      return {
        url: window.location.href,
        title: document.title,
        bodyLength: document.body.innerText.length,
        dataRows: document.querySelectorAll('tbody tr, .ag-row').length,
        tables: document.querySelectorAll('table').length,
        performance: perf
          ? {
              domContentLoaded: perf.domContentLoadedEventEnd - perf.fetchStart,
              loadComplete: perf.loadEventEnd - perf.fetchStart,
              ttfb: perf.responseStart - perf.fetchStart,
              domInteractive: perf.domInteractive - perf.fetchStart,
              nextHopProtocol: perf.nextHopProtocol,
            }
          : null,
      }
    })

    results.finalState = finalState
    results.totalTime = Date.now() - startTime
    log('capture', 'Final state captured', finalState)

    const resourceTimings = await page.evaluate(() => {
      return performance.getEntriesByType('resource').map((r) => ({
        name: r.name,
        duration: r.duration,
        transferSize: r.transferSize,
        type: r.initiatorType,
        nextHopProtocol: r.nextHopProtocol,
      }))
    })
    results.resourceTimings = resourceTimings

    try {
      const protocolCounts = {}
      for (const rt of resourceTimings) {
        if (rt && rt.nextHopProtocol) {
          protocolCounts[rt.nextHopProtocol] = (protocolCounts[rt.nextHopProtocol] || 0) + 1
        }
      }
      results.protocols = {
        navigation:
          finalState && finalState.performance ? finalState.performance.nextHopProtocol : null,
        resources: protocolCounts,
      }
      log('capture', 'Protocol summary', results.protocols)
    } catch (e) {}
  } catch (error) {
    log('error', `Fatal error: ${error.message}`)
    results.fatalError = error.message
  } finally {
    try {
      const all = Array.from(inflight.values())
      const pending = all.filter((x) => !x.finished && !x.failed)
      const completed = all.filter((x) => x.finished)
      const long = completed
        .map((x) => ({
          url: x.url,
          ms: (x.endTs ?? 0) - (x.ts ?? 0),
          type: x.type,
          protocol: x.protocol,
        }))
        .filter((x) => x.ms > 5000)
        .sort((a, b) => b.ms - a.ms)
        .slice(0, 20)
      results.longRequests = long
      results.pending = {
        count: pending.length,
        sample: pending.slice(0, 10),
      }
      log('capture', `Pending requests at end: ${results.pending.count}`)
    } catch {}

    await browser.close()

    // Save results - find project root by looking for package.json
    let projectRoot = __dirname
    while (
      !fs.existsSync(path.join(projectRoot, 'package.json')) &&
      projectRoot !== path.dirname(projectRoot)
    ) {
      projectRoot = path.dirname(projectRoot)
    }
    const outputDir = path.join(projectRoot, 'script-output')
    if (!fs.existsSync(outputDir)) {
      fs.mkdirSync(outputDir, { recursive: true })
    }
    const outputFile = path.join(outputDir, `capture_${env}_${Date.now()}.json`)
    fs.writeFileSync(outputFile, JSON.stringify(results, null, 2))
    console.log(`\nResults saved to: ${outputFile}`)

    // Quick summary
    console.log('\n=== SUMMARY ===')
    console.log(`Total time: ${results.totalTime}ms`)
    console.log(`Requests made: ${results.requests.length}`)
    console.log(`Errors: ${results.errors.length}`)
    if (results.finalState) {
      console.log(`Final URL: ${results.finalState.url}`)
      console.log(`Data rows: ${results.finalState.dataRows}`)
    }
  }
}

// Run for environment specified in command line
const env = process.argv[2] || 'uat'
if (!['production', 'uat'].includes(env)) {
  console.log('Usage: node scripts/capture_metrics.cjs [production|uat] [job-id]')
  process.exit(1)
}

const jobId = process.argv[3] || '7b22a6cf-2917-4267-9385-9c3ef2c424e1'
console.log(`Testing job: ${jobId}`)

captureMetrics(env, jobId)
