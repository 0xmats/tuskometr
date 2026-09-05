// Run with Playwright available at PLAYWRIGHT_MODULE_PATH and a built site at TEST_URL.
const assert = require('node:assert/strict')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')

async function main() {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] })
  try {
    const page = await browser.newPage()
    const start = Date.now()
    let serverTime = start
    const advance = async milliseconds => {
      serverTime += milliseconds
      await page.waitForTimeout(Math.min(milliseconds, 16000))
    }
    let version = 'a'.repeat(32)
    let manifestCalls = 0
    let jsonCalls = 0
    let fail = false
    const base = process.env.TEST_URL || 'http://127.0.0.1:32768'
    await page.route('https://www.youtube.com/**', route => route.abort())
    await page.route('**/dashboard/manifest.json', async route => {
      manifestCalls++
      await route.fulfill({ headers: { Date: new Date(serverTime).toUTCString() }, json: {
        version, generatedAt: new Date(start).toISOString(), staleAfterSeconds: 120,
        dashboards: { '1': `/dashboard/versions/${version}/1-0.json`,
          '7': `/dashboard/versions/${version}/7-0.json`,
          '30': `/dashboard/versions/${version}/30-0.json` },
      } })
    })
    await page.route('**/dashboard/versions/**', async route => {
      jsonCalls++
      if (fail) return route.fulfill({ status: 503, body: 'unavailable' })
      const label = version[0] === 'a' ? 'pierwsza publikacja' : 'druga publikacja'
      await route.fulfill({ json: {
        generatedAt: new Date(start).toISOString(),
        stats: { summary: { today: 2, last24Hours: 2, last7Days: 2 },
          range: { from: new Date(start - 86400000).toISOString(),
            to: new Date(start).toISOString(), total: 2 }, buckets: [], forms: [] },
        status: { state: 'live', updatedAt: new Date(start).toISOString(), lagSeconds: 10 },
        occurrences: { items: [{ id: 1, occurredAt: new Date(start).toISOString(),
          form: 'Tusk', quote: label, confidence: 0.9, sourceUrl: '',
          sourcePositionSeconds: null }], nextPage: null },
      } })
    })
    await page.goto(base)
    await page.getByText('pierwsza publikacja', { exact: true }).waitFor()
    assert.equal(jsonCalls, 1)
    await advance(16000)
    await page.waitForFunction(() => true)
    assert.ok(manifestCalls >= 2)
    assert.equal(jsonCalls, 1, 'unchanged manifest must not refetch dashboard JSON')
    version = 'b'.repeat(32)
    await advance(16000)
    await page.getByText('druga publikacja', { exact: true }).waitFor()
    assert.equal(jsonCalls, 2, 'new publication appears without page reload')
    fail = true
    version = 'c'.repeat(32)
    await advance(16000)
    await advance(20000)
    await page.getByText('druga publikacja', { exact: true }).waitFor()
    await page.getByRole('status').filter({ hasText: 'Nie udało się pobrać' }).waitFor()
    fail = false
    version = 'b'.repeat(32)
    await advance(16000)
    await advance(120000)
    await page.getByRole('status').filter({ hasText: 'Generator nie opublikował' }).waitFor()
    console.log('PASS: unchanged manifest, live update, last good data, stale warning')
  } finally {
    await browser.close()
  }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
