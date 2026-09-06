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
assert.equal(first.occurrences.nextPage, `${base}#1`)
const second = await api.fetchDashboard(first.occurrences.nextPage)
assert.deepEqual(second.occurrences.items, [{ id: 2 }])
assert.equal(second.occurrences.nextPage, null)
assert.equal(api.dashboardIsStale(first, manifest, manifest.receivedAtMs + 116000), true)
await assert.rejects(api.fetchDashboard('https://untrusted.example/file.json'))
assert.equal(calls.length, 4)
console.log('R2 cross-origin data, pagination and freshness checks passed')

const at = (id, time) => ({ id, occurredAt: `2026-01-01T${time}:00Z` })
const rows = [at(99, '11:20'), at(2, '12:10'), at(3, '12:10'), at(1, '13:00')]
assert.deepEqual(api.sortOccurrences([...rows, rows[0]]).map(x => x.id), [1, 3, 2, 99])
for (const days of [7, 30]) {
  assert.equal(api.rangeAvailable(days, {}, dashboard.generatedAt), false)
  const stats = { historyStartedAt: '2026-01-01T00:00:00Z' }
  const boundary = Date.parse(stats.historyStartedAt) + days * 86400000
  assert.equal(api.rangeAvailable(days, stats, new Date(boundary - 1).toISOString()), false)
  assert.equal(api.rangeAvailable(days, stats, new Date(boundary).toISOString()), true)
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
