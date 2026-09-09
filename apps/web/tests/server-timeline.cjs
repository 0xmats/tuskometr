// Built-site integration: TEST_URL and PLAYWRIGHT_MODULE_PATH follow other UI tests.
const assert = require('node:assert/strict')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')

async function main() {
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage()
    const started = Math.floor(Date.now() / 1000) * 1000
    let serverNow = started
    const origin = started / 1000 - 100000
    let sample = { videoId: 'dzntyCTgJMQ', origin, checkedAt: started / 1000,
      expiresAt: started / 1000 + 180 }
    let releaseManifest
    const manifestGate = new Promise(resolve => { releaseManifest = resolve })
    let markYouTubeStarted
    const youtubeStarted = new Promise(resolve => { markYouTubeStarted = resolve })
    const youtubeRequests = []
    const pageErrors = []
    page.on('pageerror', error => pageErrors.push(error.message))
    await page.clock.install({ time: started })
    await page.route('https://www.youtube.com/**', route => {
      youtubeRequests.push(route.request().url())
      markYouTubeStarted()
      return route.abort()
    })
    await page.route('**/dashboard/manifest.json', async route => {
      await manifestGate
      await route.fulfill({ headers: { Date: new Date(serverNow).toUTCString() }, json: {
        version: 'same-dashboard', generatedAt: new Date(serverNow).toISOString(),
        staleAfterSeconds: 120, youtubeTimeline: sample,
        dashboards: { '1': '/dashboard/test.json' },
      } })
    })
    await page.route('**/dashboard/test.json', route => route.fulfill({ json: {
      generatedAt: new Date(started).toISOString(),
      stats: { summary: { today: 1, last24Hours: 1, last7Days: 1 },
        range: { from: new Date(started - 86400000).toISOString(), to: new Date(started).toISOString(), total: 1 },
        buckets: [], forms: [] },
      status: { state: 'live', updatedAt: new Date(started).toISOString(), lagSeconds: 0 },
      occurrences: { items: [{ id: 1, occurredAt: new Date(started - 60000).toISOString(),
        form: 'Tusk', quote: 'Test fragmentu z kalibracją serwera.', confidence: 1,
        sourceUrl: 'https://www.youtube.com/watch?v=dzntyCTgJMQ', sourcePositionSeconds: null }], nextPage: null },
    } }))
    await page.goto(process.env.TEST_URL || 'http://127.0.0.1:4175')
    await page.clock.runFor(1000)
    assert.equal(youtubeRequests.length, 0, 'wait for initial manifest before browser fallback')
    releaseManifest()
    const link = page.getByRole('link', { name: 'Zobacz fragment', exact: true })
    await link.waitFor()
    assert.equal(new URL(await link.getAttribute('href')).searchParams.get('t'), '99943s')
    assert.equal(youtubeRequests.length, 0, 'fresh calibration needs no player requests')
    assert.equal(await page.locator('iframe').count(), 0)
    // Refresh the calibration while keeping the immutable dashboard version unchanged.
    sample = { ...sample, origin: origin + 2 }
    await page.clock.runFor(6000)
    await page.waitForFunction(() => document.querySelector('a[href*="t=99941s"]'))
    assert.equal(youtubeRequests.length, 0)
    // An expired sample must stop generating links and start the legacy fallback.
    serverNow += 181000
    await page.clock.fastForward(181000)
    await Promise.race([youtubeStarted, page.waitForTimeout(10000).then(() => {
      throw Error('Expiry did not start browser calibration')
    })])
    assert.ok(youtubeRequests.length > 0)
    assert.equal(await link.count(), 0)
    // Fresh server data recovers without reload, even if the browser fallback failed.
    sample = { ...sample, checkedAt: serverNow / 1000, expiresAt: serverNow / 1000 + 180 }
    await page.clock.runFor(6000)
    await link.waitFor()
    const requestCount = youtubeRequests.length
    await page.clock.runFor(20000)
    assert.equal(youtubeRequests.length, requestCount, 'server recovery cancels fallback retries')
    assert.deepEqual(pageErrors, [])
    console.log('PASS: immediate fragment links, no YouTube requests, manifest-only updates, expiry fallback and recovery')
  } finally {
    await browser.close()
  }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
