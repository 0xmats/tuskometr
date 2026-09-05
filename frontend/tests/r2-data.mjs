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
