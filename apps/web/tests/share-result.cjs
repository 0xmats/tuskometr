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
    await page.addInitScript(() => {
      window.renders = 0
      window.originalToBlob = HTMLCanvasElement.prototype.toBlob
      HTMLCanvasElement.prototype.toBlob = function (...args) {
        window.renders++
        return window.originalToBlob.apply(this, args)
      }
    })
    await page.goto(process.env.TEST_URL || 'http://127.0.0.1:3017')
    await page.locator('article').first().waitFor()
    const trigger = page.getByRole('button', { name: 'Udostępnij', exact: true })
    const panel = page.getByRole('region', { name: 'Udostępnianie' })
    await trigger.click()
    await panel.getByText('Link skopiowany', { exact: true }).waitFor()
    assert.equal(await page.evaluate(() => navigator.clipboard.readText()), new URL(page.url()).origin + '/')
    assert.equal(await page.evaluate(() => window.renders), 0, 'opening only copies the link')
    assert.equal(await panel.locator('input, img').count(), 0, 'no visible URL or preview')
    assert.equal(await panel.getByRole('button', { name: 'Pobierz PNG' }).count(), 0)
    await panel.getByRole('button', { name: 'Kopiuj obrazek' }).click()
    await panel.getByText('Obrazek skopiowany', { exact: true }).waitFor()
    const bytes = Buffer.from(await page.evaluate(async () => {
      const items = await navigator.clipboard.read()
      const blob = await items[0].getType('image/png')
      return [...new Uint8Array(await blob.arrayBuffer())]
    }))
    assert.deepEqual([...bytes.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10])
    assert.equal(bytes.readUInt32BE(16), 1200)
    assert.equal(bytes.readUInt32BE(20), 630)
    assert.equal(await page.evaluate(() => window.renders), 1)
    await page.keyboard.press('Escape')
    await panel.waitFor({ state: 'detached' })
    assert.equal(await trigger.evaluate(element => element === document.activeElement), true)
    for (const width of [320, 375, 640, 1280]) {
      await page.setViewportSize({ width, height: 812 })
      await trigger.click()
      await panel.waitFor()
      const box = await panel.boundingBox()
      assert.ok(box.x >= 0 && box.x + box.width <= width, `panel fits ${width}px screen`)
      if (width === 375) await page.screenshot({ path: '/tmp/tuskometr-share-compact.png' })
      await page.locator('h1').click()
      await panel.waitFor({ state: 'detached' })
    }
    await page.evaluate(() => {
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async () => { throw new Error('denied') } } })
    })
    await trigger.click()
    await panel.getByLabel('Link do strony').waitFor()
    assert.equal(await panel.getByLabel('Link do strony').inputValue(), new URL(page.url()).origin + '/')
    await page.evaluate(() => { HTMLCanvasElement.prototype.toBlob = callback => callback(null) })
    await panel.getByRole('button', { name: 'Kopiuj obrazek' }).click()
    await panel.getByRole('alert').waitFor()
    await page.evaluate(() => { HTMLCanvasElement.prototype.toBlob = window.originalToBlob })
    await panel.getByRole('button', { name: 'Kopiuj obrazek' }).click()
    await panel.getByText('Nie można skopiować obrazka. Możesz go pobrać.').waitFor()
    const retried = page.waitForEvent('download')
    await panel.getByRole('button', { name: 'Pobierz PNG' }).click()
    const fallbackBytes = await fs.readFile(await (await retried).path())
    assert.equal(fallbackBytes.readUInt32BE(16), 1200)
    assert.equal(await panel.getByRole('alert').count(), 0)
    assert.deepEqual(errors, [])
    console.log('Compact share: immediate copy, image clipboard, on-demand PNG fallback, keyboard/outside dismissal, mobile, clipboard fallback and retry passed')
  } finally { await browser.close() }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
