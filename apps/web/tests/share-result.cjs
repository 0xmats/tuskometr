// Against the offline Vite fixture; override PLAYWRIGHT_MODULE_PATH and TEST_URL as needed.
const assert = require('node:assert/strict')
const fs = require('node:fs/promises')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')

async function main() {
  const browser = await chromium.launch({ args: ['--no-sandbox'] })
  try {
    const context = await browser.newContext({ permissions: ['clipboard-read', 'clipboard-write'] })
    const page = await context.newPage()
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.goto(process.env.TEST_URL || 'http://127.0.0.1:3017')
    const button = page.getByRole('button', { name: 'Udostępnij wynik', exact: true })
    await button.click()
    const dialog = page.getByRole('dialog')
    await dialog.locator('img').waitFor({ state: 'visible' })
    const preview = await dialog.locator('img').getAttribute('src')
    assert.ok(preview.startsWith('blob:'), 'preview is created locally')
    const link = await page.getByLabel('Link do aktualnej strony').inputValue()
    assert.equal(link, new URL(page.url()).origin + '/')
    await page.getByRole('button', { name: 'Kopiuj link', exact: true }).click()
    assert.equal(await page.evaluate(() => navigator.clipboard.readText()), link)
    const downloadEvent = page.waitForEvent('download')
    await page.getByRole('link', { name: 'Pobierz PNG', exact: true }).click()
    const bytes = await fs.readFile(await (await downloadEvent).path())
    assert.deepEqual([...bytes.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10])
    assert.equal(bytes.readUInt32BE(16), 1200)
    assert.equal(bytes.readUInt32BE(20), 630)
    // The shared link opens the real live dashboard, without embedded statistics.
    const shared = await context.newPage()
    await shared.goto(link)
    await shared.locator('article').first().waitFor()
    await shared.getByRole('button', { name: 'Udostępnij wynik' }).waitFor()
    await shared.close()
    await page.keyboard.press('Escape')
    await dialog.waitFor({ state: 'detached' })
    assert.equal(await button.evaluate(element => element === document.activeElement), true)
    // Native sharing includes the ready PNG when file sharing is supported.
    await page.evaluate(() => {
      window.sharedData = null
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async () => { throw new Error('denied') } } })
      Object.defineProperty(navigator, 'canShare', { configurable: true, value: () => true })
      Object.defineProperty(navigator, 'share', { configurable: true, value: async data => { window.sharedData = data } })
    })
    await button.click()
    await dialog.locator('img').waitFor()
    await page.getByRole('button', { name: 'Udostępnij…' }).click()
    assert.equal(await page.evaluate(() => window.sharedData.files[0].type), 'image/png')
    assert.equal(await page.evaluate(() => window.sharedData.url), link)
    await page.getByRole('button', { name: 'Kopiuj link' }).click()
    await page.getByText('Zaznacz i skopiuj link z pola poniżej.').waitFor()
    await page.keyboard.press('Escape')
    await page.evaluate(() => { Object.defineProperty(navigator, 'canShare', { configurable: true, value: () => false }) })
    await button.click()
    await page.getByRole('button', { name: 'Udostępnij…' }).click()
    assert.equal(await page.evaluate(() => window.sharedData.files), undefined)
    await page.keyboard.press('Escape')
    await page.setViewportSize({ width: 375, height: 812 })
    await button.click()
    await dialog.locator('img').waitFor()
    assert.equal(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth), true)
    await page.screenshot({ path: '/tmp/tuskometr-share-client-mobile.png' })
    const frozenDescription = await page.locator('#share-description').textContent()
    await page.route('**/dashboard/manifest.json', async route => {
      const response = await route.fetch()
      const manifest = await response.json()
      manifest.version += '-next'
      for (const key of Object.keys(manifest.dashboards)) manifest.dashboards[key] += '?next=1'
      await route.fulfill({ response, json: manifest })
    })
    await page.route('**/*.json?next=1', async route => {
      const response = await route.fetch()
      const dashboard = await response.json()
      dashboard.stats.summary.lastHour = 999
      await route.fulfill({ response, json: dashboard })
    })
    await page.waitForFunction(() => document.querySelector('[aria-label="Tusków na godzinę"]').textContent.includes('999'))
    assert.equal(await page.locator('#share-description').textContent(), frozenDescription)
    assert.equal(await page.getByLabel('Link do aktualnej strony').inputValue(), link)
    // Failed local rendering can be retried; copying the link still works.
    await page.keyboard.press('Escape')
    await page.evaluate(() => {
      window.originalToBlob = HTMLCanvasElement.prototype.toBlob
      HTMLCanvasElement.prototype.toBlob = callback => callback(null)
    })
    await button.click()
    await page.getByRole('alert').filter({ hasText: 'Nie udało się utworzyć obrazka' }).waitFor()
    assert.ok(await page.getByLabel('Link do aktualnej strony').inputValue())
    await page.evaluate(() => { HTMLCanvasElement.prototype.toBlob = window.originalToBlob })
    await page.getByRole('button', { name: 'Spróbuj ponownie' }).click()
    await dialog.locator('img').waitFor()
    assert.deepEqual(errors, [])
    console.log('Client share: PNG, native file/link sharing, clipboard, mobile, frozen results, retry, and clean live-site link passed')
  } finally { await browser.close() }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
