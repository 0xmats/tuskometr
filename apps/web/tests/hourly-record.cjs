// Run against the offline Vite fixture with TEST_URL and PLAYWRIGHT_MODULE_PATH.
const assert = require('node:assert/strict')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')

async function main() {
  const browser = await chromium.launch({
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    args: ['--no-sandbox'],
  })
  try {
    for (const width of [1440, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 1000 }, reducedMotion: 'reduce' })
      const errors = []
      const recordRequests = []
      page.on('pageerror', error => errors.push(error.message))
      page.on('request', request => {
        if (/\/record-\d+\.json$/.test(request.url())) recordRequests.push(request.url())
      })
      await page.goto(process.env.TEST_URL || 'http://127.0.0.1:5187')
      const button = page.getByRole('button', { name: /Pokaż wszystkie fragmenty rekordu/ })
      await button.waitFor()
      await page.getByText(/Zbieramy dane od/).waitFor()
      assert.equal(recordRequests.length, 0, 'record quotes load only after clicking')
      const count = Number((await button.getAttribute('aria-label')).match(/: (\d+) wzmianek/)[1])
      await button.focus()
      await page.keyboard.press('Enter')
      await page.getByText(new RegExp(`Pokazano \\d+ z ${count} fragmentów rekordu`)).waitFor()
      const more = page.getByRole('button', { name: 'Pokaż kolejne 10', exact: true })
      while (await more.count()) {
        const before = await page.locator('[data-occurrence-id]').count()
        await more.click()
        await page.waitForFunction(previous =>
          document.querySelectorAll('[data-occurrence-id]').length > previous, before)
      }
      assert.equal(await page.locator('[data-occurrence-id]').count(), count)
      const ids = await page.locator('[data-occurrence-id]').evaluateAll(
        elements => elements.map(element => element.dataset.occurrenceId))
      assert.equal(new Set(ids).size, count)
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
      await page.getByRole('button', { name: 'Wróć do live', exact: true }).click()
      await page.getByText('Najnowsze wzmianki według czasu wystąpienia', { exact: true }).waitFor()
      await button.scrollIntoViewIfNeeded()
      await page.screenshot({ path: `/tmp/tuskometr-record-${width}.png`, fullPage: true })
      assert.deepEqual(errors, [])
      console.log(`Record UI ${width}px: keyboard selection, all ${count} fragments, return to live, no overflow`)
      await page.close()
    }
  } finally {
    await browser.close()
  }
}

main().catch(error => { console.error(error); process.exitCode = 1 })
