// Real browser check against the running local service, without mocked responses.
const assert = require('node:assert/strict')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')

async function main() {
  const browser = await chromium.launch({ args: ['--no-sandbox'] })
  try {
    for (const skew of [600000, -600000, 0]) {
      const page = await browser.newPage()
      const errors = []
      const versions = new Set()
      page.on('pageerror', error => errors.push(error.message))
      page.on('response', async response => {
        if (response.url().endsWith('/manifest.json') && response.ok()) {
          versions.add((await response.json()).version)
        }
      })
      await page.addInitScript(offset => {
        const original = Date.now
        Date.now = () => original() + offset
      }, skew)
      await page.goto(process.env.TEST_URL || 'http://100.80.64.94:3003')
      await page.locator('article').first().waitFor()
      assert.equal(await page.getByRole('status').count(), 0)
      for (const label of ['24 godz.', '30 dni', '7 dni']) {
        await page.getByRole('button', { name: label, exact: true }).click()
        await page.locator('article').first().waitFor()
      }
      if (skew === 0) {
        await page.getByRole('button', { name: 'Pokaż kolejne 10' }).click()
        await page.waitForFunction(() => document.querySelectorAll('article').length === 20)
        await page.waitForTimeout(35000)
        assert.ok(versions.size >= 2, 'must receive a new publication automatically')
      }
      assert.equal(await page.getByRole('status').count(), 0)
      assert.deepEqual(errors, [])
      console.log(JSON.stringify({ clientClockOffsetMs: skew, warnings: 0,
        jsErrors: errors.length, observedVersions: versions.size }))
      await page.close()
    }
  } finally {
    await browser.close()
  }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
