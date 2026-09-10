// Built-site integration: run against Vite preview with PLAYWRIGHT_MODULE_PATH set.
const assert = require('node:assert/strict')
const fs = require('node:fs/promises')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const site = process.env.TEST_URL || 'http://127.0.0.1:4175'

async function main() {
  const browser = await chromium.launch({ headless: true })
  try {
    for (const mode of ['native', 'cancel', 'native-error', 'clipboard', 'denied', 'render-error', 'missing']) {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
      const errors = []
      const writes = []
      page.on('pageerror', error => errors.push(error.message))
      page.on('request', request => {
        if (request.method() !== 'GET') writes.push(request.url())
      })
      await page.addInitScript(mode => {
        window.shared = []
        window.copiedImages = []
        window.copiedLinks = []
        window.drawnImages = 0
        const toBlob = HTMLCanvasElement.prototype.toBlob
        HTMLCanvasElement.prototype.toBlob = function (...args) {
          window.drawnImages++
          if (mode === 'render-error') return args[0](null)
          return toBlob.apply(this, args)
        }
        Object.defineProperty(navigator, 'clipboard', { configurable: true, value: {
          write: async items => {
            if (mode === 'denied') throw new DOMException('Denied', 'NotAllowedError')
            if (items.length !== 1) throw new Error('Expected exactly one clipboard item')
            const blob = await items[0].getType('image/png')
            window.copiedImages.push([...new Uint8Array(await blob.arrayBuffer())])
          },
          writeText: async text => {
            if (mode === 'denied') throw new DOMException('Denied', 'NotAllowedError')
            window.copiedLinks.push(text)
          },
        } })
        Object.defineProperty(navigator, 'canShare', { configurable: true,
          value: data => ['native', 'cancel', 'native-error'].includes(mode) && data.files?.[0]?.type === 'image/png' })
        Object.defineProperty(navigator, 'share', { configurable: true, value: async data => {
          window.shared.push({ title: data.title, text: data.text, url: data.url,
            files: data.files.map(file => ({ name: file.name, type: file.type, size: file.size })) })
          if (mode === 'cancel') throw new DOMException('Canceled', 'AbortError')
          if (mode === 'native-error') throw new DOMException('Denied', 'NotAllowedError')
          await new Promise(resolve => { window.finishShare = resolve })
        } })
      }, mode)
      const now = Date.now()
      const generatedAt = new Date(now).toISOString()
      await page.route('**/dashboard/manifest.json', route => route.fulfill({
        headers: { Date: new Date(now).toUTCString() }, json: {
          version: 'share-test', generatedAt, staleAfterSeconds: 120,
          youtubeTimeline: { videoId: 'dzntyCTgJMQ', origin: now / 1000 - 100000,
            checkedAt: now / 1000, expiresAt: now / 1000 + 180 },
          dashboards: { '1': '/dashboard/share-test.json' },
        },
      }))
      await page.route('**/dashboard/share-test.json', route => route.fulfill({ json: {
        generatedAt,
        stats: { summary: { lastHour: mode === 'missing' ? null : mode === 'clipboard' ? 0 : 42,
          today: 150, last24Hours: 321, last7Days: 500 },
          range: { from: new Date(now - 86400000).toISOString(), to: generatedAt, total: 321 },
          buckets: [], forms: [] },
        status: { state: 'live', updatedAt: generatedAt, lagSeconds: 0 },
        occurrences: { items: [], nextPage: null },
      } }))
      await page.goto(`${site}/?tracking=test#overview`)
      await page.getByText('150', { exact: true }).waitFor()
      const button = page.getByRole('button', { name: 'Udostępnij wynik', exact: true })
      assert.equal(await page.evaluate(() => window.drawnImages), 0, 'no image before clicking')
      if (mode === 'missing') {
        assert.equal(await button.isDisabled(), true)
        await page.close()
        continue
      }
      await button.click()
      const dialog = page.getByRole('dialog', { name: 'Udostępnij wynik' })
      await dialog.waitFor()
      if (mode === 'render-error') {
        await dialog.getByRole('alert').waitFor()
        assert.equal(await dialog.getByRole('button', { name: 'Kopiuj obrazek' }).isDisabled(), true)
        assert.equal(await dialog.getByRole('link', { name: 'Pobierz' }).count(), 0)
      } else {
        const preview = dialog.getByRole('img')
        await preview.waitFor()
        assert.equal(await preview.evaluate(img => img.naturalWidth), 1080)
        assert.equal(await preview.evaluate(img => img.naturalHeight), 1440)
        assert.equal(await page.evaluate(() => window.drawnImages), 1)
        if (['native', 'cancel', 'native-error'].includes(mode)) {
          const share = dialog.getByRole('button', { name: 'Udostępnij', exact: true })
          if (mode === 'native') {
            await dialog.getByRole('button', { name: 'Kopiuj obrazek', exact: true }).click()
            await dialog.getByRole('status').filter({ hasText: 'Obrazek skopiowany' }).waitFor()
            assert.equal(await page.evaluate(() => window.shared.length), 0, 'direct copy bypasses OS sharing')
            assert.equal(await page.evaluate(() => window.copiedImages.length), 1)
          }
          await share.evaluate(button => { button.click(); button.click() })
          if (mode === 'native') {
            await page.waitForFunction(() => typeof window.finishShare === 'function')
            assert.equal(await share.isDisabled(), true)
            assert.equal(await page.evaluate(() => window.shared.length), 1, 'rapid clicks share only once')
            const data = await page.evaluate(() => window.shared[0])
            assert.equal(data.files.length, 1)
            assert.equal(data.files[0].type, 'image/png')
            assert.ok(data.files[0].size > 1000)
            assert.equal(data.title, undefined)
            assert.equal(data.text, undefined)
            assert.equal(data.url, undefined)
            await page.evaluate(() => window.finishShare())
          } else if (mode === 'native-error') {
            await dialog.getByRole('alert').waitFor()
          } else {
            await page.waitForFunction(() => window.shared.length === 1 &&
              !Array.from(document.querySelectorAll('dialog button')).find(b => b.getAttribute('aria-label') === 'Udostępnij').disabled)
            assert.equal(await dialog.getByRole('alert').count(), 0)
          }
          assert.equal(await page.evaluate(() => window.copiedImages.length), mode === 'native' ? 1 : 0)
        } else {
          await dialog.getByRole('button', { name: 'Kopiuj obrazek', exact: true }).click()
          if (mode === 'denied') await dialog.getByRole('alert').waitFor()
          else {
            await dialog.getByRole('status').filter({ hasText: 'Obrazek skopiowany' }).waitFor()
            assert.equal(await page.evaluate(() => window.copiedImages.length), 1)
            const bytes = Buffer.from(await page.evaluate(() => window.copiedImages[0]))
            assert.equal(bytes.readUInt32BE(16), 1080)
            assert.equal(bytes.readUInt32BE(20), 1440)
          }
          assert.equal(await dialog.getByRole('link', { name: 'Pobierz' }).count(), 0)
          await dialog.getByRole('button', { name: 'Kopiuj link', exact: true }).click()
          if (mode === 'denied') {
            const input = dialog.getByRole('textbox', { name: 'Skopiuj link:' })
            await input.waitFor()
            assert.equal(await input.inputValue(), `${new URL(site).origin}/`)
          } else {
            await dialog.getByRole('status').filter({ hasText: 'Link skopiowany' }).waitFor()
            assert.deepEqual(await page.evaluate(() => window.copiedLinks), [`${new URL(site).origin}/`])
            const linkButton = dialog.getByRole('button', { name: 'Kopiuj link', exact: true })
            const confirmation = linkButton.locator('span.absolute')
            assert.ok((await confirmation.getAttribute('class')).includes('opacity-100'))
            await page.waitForTimeout(2000)
            assert.ok((await confirmation.getAttribute('class')).includes('opacity-0'))
          }
        }
        if (mode === 'native') {
          const imageBytes = await preview.evaluate(async img => [...new Uint8Array(await (await fetch(img.src)).arrayBuffer())])
          await fs.writeFile('/tmp/tuskometr-share-card.png', Buffer.from(imageBytes))
          for (const width of [320, 375, 640, 1280]) {
            await page.setViewportSize({ width, height: 900 })
            const box = await dialog.boundingBox()
            assert.ok(box.x >= 0 && box.x + box.width <= width, `dialog fits ${width}px viewport`)
            assert.equal(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth), true)
            if (width === 375) await page.screenshot({ path: '/tmp/tuskometr-share-mobile.png' })
          }
        }
      }
      await page.keyboard.press('Escape')
      assert.equal(await dialog.isVisible(), false)
      assert.equal(await button.evaluate(el => document.activeElement === el), true)
      assert.deepEqual(writes, [])
      assert.deepEqual(errors, [])
      await page.close()
    }
    console.log('PASS: on-demand PNG preview, native image sharing, cancellation, image clipboard, button feedback, link copy, mobile and no writes')
  } finally { await browser.close() }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
