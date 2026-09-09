import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'
const source = readFileSync(new URL('../src/lib/server-timeline.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
})
const { serverTimelineOrigin } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
const video = 'dzntyCTgJMQ'
const checked = 1800000000
const sample = { videoId: video, origin: checked - 100000, checkedAt: checked, expiresAt: checked + 180 }
const manifest = { youtubeTimeline: sample, serverTimeAtReceiptMs: checked * 1000, receivedAtMs: 1000 }
const get = (data = manifest, now = 1000) => serverTimelineOrigin(data, video, now)
assert.equal(get(), sample.origin)
assert.equal(get(manifest, 180999), sample.origin)
assert.equal(get(manifest, 181000), null, 'expires even without another manifest')
assert.equal(serverTimelineOrigin(undefined, video, 1000), null)
for (const value of [null, {}, { ...sample, videoId: 'other' }, { ...sample, origin: NaN },
  { ...sample, origin: -1 }, { ...sample, origin: '1' }, { ...sample, checkedAt: checked + 5 },
  { ...sample, expiresAt: checked + 301 }]) {
  assert.equal(get({ ...manifest, youtubeTimeline: value }), null)
}
assert.equal(get({ ...manifest, youtubeTimeline: { ...sample, checkedAt: checked + 0.8 } }), sample.origin,
  'HTTP Date rounds down to whole seconds')
// Device wall-clock changes do not affect server calibration freshness.
const originalNow = Date.now
Date.now = () => 0
assert.equal(get(), sample.origin)
Date.now = () => Number.MAX_SAFE_INTEGER
assert.equal(get(), sample.origin)
Date.now = originalNow
console.log('Server timeline: expiry, source identity, invalid data and clock skew passed')
