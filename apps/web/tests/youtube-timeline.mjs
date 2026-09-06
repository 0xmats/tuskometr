import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'
const source = readFileSync(new URL('../src/lib/youtube-timeline.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
})
let scenarioId = 0
async function scenario(mode) {
  let now = 0, serial = 0, created = 0, destroyed = 0, scripts = 0
  const timers = new Map(), elements = new Set(), updates = []
  const timer = (fn, delay, interval = false) => {
    const id = ++serial
    timers.set(id, { fn, at: now + delay, delay, interval })
    return id
  }
  const win = {
    location: { origin: 'https://test.example' },
    setTimeout: (fn, delay) => timer(fn, delay), clearTimeout: id => timers.delete(id),
    setInterval: (fn, delay) => timer(fn, delay, true), clearInterval: id => timers.delete(id),
  }
  const api = { Player: class {
    constructor(mount, options) {
      created++
      this.options = options
      const attempt = created
      win.setTimeout(() => {
        if (mode === 'error' || (mode === 'recover' && attempt === 1)) options.events.onError()
        else if (mode === 'blocked') options.events.onAutoplayBlocked()
        else if (mode !== 'no-ready') options.events.onReady({ target: this })
      }, 0)
    }
    mute() {}
    playVideo() { if (mode === 'throw') throw Error('player failed') }
    getDuration() { return mode === 'no-metadata' ? 0 : 5000 }
    seekTo() {}
    getCurrentTime() { return mode === 'invalid-position' ? NaN : 4990 }
    destroy() { destroyed++ }
  } }
  if (!mode.startsWith('script')) win.YT = api
  globalThis.window = win
  globalThis.document = {
    createElement: () => {
      const element = { style: {}, setAttribute() {}, remove() { elements.delete(element) } }
      return element
    },
    body: { append: el => elements.add(el) },
    head: { append: el => {
      elements.add(el); scripts++
      if (mode === 'script-error') win.setTimeout(() => el.onerror(), 0)
      if (mode === 'script-recover') win.setTimeout(() => {
        if (scripts === 1) el.onerror()
        else { win.YT = api; win.onYouTubeIframeAPIReady() }
      }, 0)
    } },
  }
  const { startYouTubeTimeline } = await import(`data:text/javascript;base64,${Buffer.from(outputText + `\n// ${scenarioId++}`).toString('base64')}`)
  const flush = async () => { for (let i = 0; i < 10; i++) await Promise.resolve() }
  const advance = async ms => {
    const end = now + ms
    await flush()
    while (true) {
      const next = [...timers].filter(([, t]) => t.at <= end).sort((a, b) => a[1].at - b[1].at)[0]
      if (!next) break
      const [id, t] = next
      now = t.at
      if (t.interval) t.at += t.delay
      else timers.delete(id)
      t.fn()
      await flush()
    }
    now = end
  }
  const stop = startYouTubeTimeline('test', state => updates.push(state))
  return { advance, stop, updates, timers, elements, win, api,
    counts: () => ({ created, destroyed, scripts }),
    restart: () => startYouTubeTimeline('test', state => updates.push(state)) }
}
for (const mode of ['success', 'recover', 'script-recover']) {
  const s = await scenario(mode)
  await s.advance(90_000)
  assert.equal(s.updates.at(-1).status, 'ready', mode)
  assert.ok(Number.isFinite(s.updates.at(-1).origin))
  assert.equal(s.counts().created, s.counts().destroyed)
  assert.equal(s.timers.size, 0)
  s.stop()
}
for (const mode of ['error', 'blocked', 'no-ready', 'no-metadata', 'invalid-position', 'throw', 'script-error', 'script-timeout']) {
  const s = await scenario(mode)
  await s.advance(90_000)
  assert.equal(s.updates.at(-1).status, 'error', mode)
  assert.equal(mode.startsWith('script') ? s.counts().scripts : s.counts().created, 3, mode)
  assert.equal(s.counts().created, s.counts().destroyed)
  assert.equal(s.elements.size, 0)
  assert.equal(s.timers.size, 0)
  s.stop()
  // Manual retry starts a fresh attempt budget and can recover a failed script.
  if (mode === 'script-error') {
    s.win.YT = s.api
    const stop = s.restart()
    await s.advance(3000)
    assert.equal(s.updates.at(-1).status, 'ready')
    stop()
  }
}
for (const mode of ['no-metadata', 'script-timeout', 'recover']) {
  const s = await scenario(mode)
  await s.advance(500)
  s.stop()
  const count = s.updates.length
  await s.advance(90_000)
  assert.equal(s.updates.length, count, 'disposed sessions cannot update or retry')
  assert.equal(s.timers.size, 0)
  assert.equal(s.counts().created, s.counts().destroyed)
}
console.log('YouTube calibration: recovery, timeouts, blocked playback, invalid positions, manual retry and cleanup passed')
