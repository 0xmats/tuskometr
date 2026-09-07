// Run against Vite with TEST_URL and a locally available PLAYWRIGHT_MODULE_PATH.
const assert = require('node:assert/strict')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')

async function main() {
  const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH, args: ['--no-sandbox'] })
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
    const start = Date.parse('2026-09-06T14:00:00Z')
    const buckets = Array.from({ length: 25 }, (_, index) => ({
      start: new Date(start + index * 3600000).toISOString(),
      end: new Date(start + (index + 1) * 3600000).toISOString(),
      count: index === 0 ? 4 : index === 24 ? 22 : 10,
    }))
    const generatedAt = buckets[24].end
    await page.route('**/dashboard/**', route => route.fulfill({
      json: route.request().url().endsWith('manifest.json')
        ? { version: 'tooltip-test', generatedAt, staleAfterSeconds: 120,
          dashboards: { 1: '/dashboard/test.json' } }
        : { generatedAt, stats: { summary: { today: 22, last24Hours: 266, last7Days: 266 },
          range: { from: buckets[0].start, to: generatedAt, total: 266 }, buckets, forms: [] },
          status: { state: 'offline', updatedAt: generatedAt },
          occurrences: { items: [], nextPage: null } },
      headers: { Date: new Date(generatedAt).toUTCString() },
    }))
    await page.goto(process.env.TEST_URL || 'http://127.0.0.1:5187')
    const bands = page.locator('[data-chart-band]')
    await bands.last().waitFor()
    for (const [index, count, date] of [[0, 4, '6 września'], [24, 22, '7 września']]) {
      await bands.nth(index).hover({ force: true })
      const tooltip = page.locator('.recharts-tooltip-wrapper')
      await tooltip.waitFor({ state: 'visible' })
      const text = await tooltip.innerText()
      assert.match(text, new RegExp(`Wystąpienia\\s+${count}\\b`))
      assert.ok(text.includes(date), text)
      assert.ok(text.includes('16:00'), text)
    }
    console.log('Repeated hour labels: first and last bars show their own counts and dates')
  } finally {
    await browser.close()
  }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
