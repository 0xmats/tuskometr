import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'

const source = readFileSync(new URL('../src/lib/api.ts', import.meta.url), 'utf8')
  .replace('import.meta.env.VITE_DATA_ORIGIN', '"https://data.example.com"')
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
})
const api = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
const calls = []
const base = '/dashboard/objects/dashboard.json'
const dashboard = {
  generatedAt: '2026-01-01T00:00:00Z', stats: {}, status: {},
  occurrences: { items: [{ id: 3 }], nextPage: null },
  historyPages: ['/dashboard/objects/older.json'],
}
globalThis.fetch = async (url) => {
  calls.push(url)
  assert.ok(url.startsWith('https://data.example.com/dashboard/'))
  if (url.endsWith('manifest.json')) return new Response(JSON.stringify({
    generatedAt: dashboard.generatedAt, version: 'v1', staleAfterSeconds: 120,
    dashboards: { 7: base },
  }), { headers: { Date: 'Thu, 01 Jan 2026 00:00:00 GMT', Age: '5' } })
  return new Response(JSON.stringify(url.endsWith('older.json') ? { items: [{ id: 2 }] } : dashboard))
}
const manifest = await api.fetchManifest()
assert.equal(manifest.serverTimeAtReceiptMs, Date.parse(dashboard.generatedAt) + 5000)
const first = await api.fetchDashboard(manifest.dashboards['7'])
assert.deepEqual(first.occurrences.items, [{ id: 3 }, { id: 2 }])
assert.equal(first.occurrences.nextPage, null)
assert.equal(api.dashboardIsStale(first, manifest, manifest.receivedAtMs + 116000), true)
await assert.rejects(api.fetchDashboard('https://untrusted.example/file.json'))
assert.equal(calls.length, 3)
console.log('R2 cross-origin data, pagination and freshness checks passed')

const at = (id, time) => ({ id, occurredAt: `2026-01-01T${time}:00Z` })
const rows = [at(99, '11:20'), at(2, '12:10'), at(3, '12:10'), at(1, '13:00')]
assert.deepEqual(api.sortOccurrences([...rows, rows[0]]).map(x => x.id), [1, 3, 2, 99])
for (const days of [0, 1]) {
  assert.equal(api.rangeAvailable(days, undefined), true)
  assert.equal(api.rangeAvailable(days, { historyStartedAt: dashboard.generatedAt }, dashboard.generatedAt), true)
}
for (const days of [7, 30]) {
  assert.equal(api.rangeAvailable(days, {}, dashboard.generatedAt), false)
  const stats = { historyStartedAt: '2026-01-01T00:00:00Z' }
  const boundary = Date.parse(stats.historyStartedAt) + (days === 7 ? 1 : 7) * 86400000
  assert.equal(api.rangeAvailable(days, stats, new Date(boundary - 1).toISOString()), false)
  assert.equal(api.rangeAvailable(days, stats, new Date(boundary).toISOString()), false)
  assert.equal(api.rangeAvailable(days, stats, new Date(boundary + 1).toISOString()), true)
}
const start = '2026-01-01T12:00:00Z'
const end = '2026-01-01T13:00:00Z'
const bucket = { ...dashboard, bucketPages: { [start]: ['/dashboard/a.json', '/dashboard/b.json'] } }
const requested = []
globalThis.fetch = async url => {
  requested.push(url)
  return new Response(JSON.stringify({ items: url.endsWith('a.json') ? rows.slice(0, 2) : rows.slice(2) }))
}
assert.deepEqual((await api.fetchBucketOccurrences(bucket, start, end)).map(x => x.id), [3, 2])
assert.equal(requested.length, 2)
assert.deepEqual(await api.fetchBucketOccurrences({ ...bucket, bucketPages: { [start]: [] } }, start, end), [])
assert.equal(requested.length, 2)
globalThis.fetch = async () => new Response('', { status: 503 })
await assert.rejects(api.fetchBucketOccurrences(bucket, start, end), /503/)
console.log('Chronological backfill, complete bucket filtering and range availability checks passed')

// A UI page spans storage chunks, including singletons left by backfill.
for (const sizes of [[1, 30, 30, 4], Array(65).fill(1), [30, 30, 5], [0, 0, 30, 0, 1]]) {
  let id = 1000
  const chunks = sizes.map(size => Array.from({ length: size }, () => ({ id: id-- })))
  const snapshot = { ...dashboard, occurrences: { items: chunks[0], nextPage: null },
    historyPages: chunks.slice(1).map((_, i) => `/dashboard/chunk-${i + 1}.json`) }
  globalThis.fetch = async url => {
    const match = url.match(/chunk-(\d+)\.json$/)
    return new Response(JSON.stringify(match ? { items: chunks[Number(match[1])] } : snapshot))
  }
  const collected = []
  let next = base
  while (next) {
    const page = await api.fetchDashboard(next)
    assert.ok(page.occurrences.items.length <= 10)
    if (page.occurrences.nextPage) assert.equal(page.occurrences.items.length, 10)
    collected.push(...page.occurrences.items)
    next = page.occurrences.nextPage
  }
  assert.deepEqual(collected, chunks.flat())
  await assert.rejects(api.fetchDashboard(`${base}#1:999`), /Nieprawidłowa/)
}
console.log('10-item pages across storage boundaries without skipped or duplicated mentions passed')

for (const [age, weekly, monthly] of [[2, '2 dni', '2 dni'], [3, '3 dni', '3 dni'],
  [7, '7 dni', '7 dni'], [7.1, '7 dni', '8 dni'], [9, '7 dni', '9 dni'],
  [30, '7 dni', '30 dni'], [40, '7 dni', '30 dni']]) {
  const stats = { historyStartedAt: '2026-01-01T00:00:00Z' }
  const now = new Date(Date.parse(stats.historyStartedAt) + age * 86400000).toISOString()
  assert.equal(api.rangeLabel(7, stats, now), weekly)
  assert.equal(api.rangeLabel(30, stats, now), monthly)
}
// A selected day must not download every storage chunk before showing ten rows.
for (const sizes of [[30, 30, 5], [1, 2, 4, 30], [10, 10], [0]]) {
  let id = 1000
  const chunks = sizes.map(size => Array.from({ length: size }, () => at(id--, '12:30')))
  const urls = chunks.map((_, i) => `/dashboard/bucket-${i}.json`)
  const requested = []
  globalThis.fetch = async url => {
    requested.push(url)
    return new Response(JSON.stringify({ items: chunks[Number(url.match(/bucket-(\d+)/)[1])] }))
  }
  const snapshot = { ...dashboard, bucketPages: { [start]: urls } }
  const first = await api.fetchBucketOccurrencePage(snapshot, start, end)
  assert.deepEqual(first.items, chunks.flat().slice(0, 10))
  if (sizes[0] >= 10) assert.equal(requested.length, 1)
  const collected = [...first.items]
  let next = first.nextCursor
  while (next) {
    const page = await api.fetchBucketOccurrencePage(snapshot, start, end, next)
    assert.ok(page.items.length <= 10)
    collected.push(...page.items)
    next = page.nextCursor
  }
  assert.deepEqual(collected, chunks.flat())
}
// Static (non-R2) pages also expose ten rows without losing the rest of a chunk.
const legacyRows = Array.from({ length: 35 }, (_, id) => at(id, '12:30'))
globalThis.fetch = async url => new Response(JSON.stringify({ ...dashboard, historyPages: undefined,
  occurrences: { items: url.endsWith('older.json') ? legacyRows.slice(30) : legacyRows.slice(0, 30),
    nextPage: url.endsWith('older.json') ? null : '/dashboard/older.json' } }))
let legacyNext = base
const legacyCollected = []
while (legacyNext) {
  const page = await api.fetchDashboard(legacyNext)
  assert.ok(page.occurrences.items.length <= 10)
  legacyCollected.push(...page.occurrences.items)
  legacyNext = page.occurrences.nextPage
}
assert.deepEqual(legacyCollected, legacyRows)
console.log('Dynamic range labels and lazy ten-item bucket/static pagination passed')
