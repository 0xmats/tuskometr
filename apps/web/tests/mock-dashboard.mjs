import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'

async function loadTs(relativePath) {
  const source = readFileSync(new URL(relativePath, import.meta.url), 'utf8')
    .replace('import.meta.env.VITE_DATA_ORIGIN', '""')
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
  })
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
}

const { buildMockDashboard } = await loadTs('../dev/mock-dashboard.ts')
const api = await loadTs('../src/lib/api.ts')
const fixture = JSON.parse(readFileSync(new URL('../dev/dashboard.json', import.meta.url)))
const now = Date.parse('2026-09-06T12:00:00Z')
const routes = buildMockDashboard(fixture, now)
globalThis.fetch = async path => {
  assert.ok(path.startsWith('/dashboard/'), 'mock requests must remain local')
  assert.ok(routes.has(path), `missing fixture route: ${path}`)
  return new Response(JSON.stringify(routes.get(path)), { headers: { Date: new Date(now).toUTCString() } })
}
const manifest = await api.fetchManifest()
for (const days of [0, 1, 7, 30]) {
  const dashboard = await api.fetchDashboard(manifest.dashboards[days])
  assert.equal(api.dashboardIsStale(dashboard, manifest, manifest.receivedAtMs), false)
  assert.equal(api.rangeAvailable(days, dashboard.stats, dashboard.generatedAt), true)
  const items = [...dashboard.occurrences.items]
  let next = dashboard.occurrences.nextPage
  while (next) {
    const page = await api.fetchDashboard(next)
    items.push(...page.occurrences.items)
    next = page.occurrences.nextPage
  }
  const duration = days === 0 ? 60 : days * 24 * 60
  const expected = fixture.occurrences.filter(item => item.minutesAgo <= duration).length
  assert.equal(items.length, expected)
  assert.equal(new Set(items.map(item => item.id)).size, expected)
  assert.equal(dashboard.stats.range.total, expected)
  assert.equal(dashboard.stats.forms.reduce((sum, form) => sum + form.count, 0), expected)
  let bucketTotal = 0
  for (const bucket of dashboard.stats.buckets) {
    const rows = await api.fetchBucketOccurrences(dashboard, bucket.start, bucket.end)
    assert.equal(rows.length, bucket.count)
    bucketTotal += rows.length
  }
  assert.equal(bucketTotal, expected)
}
console.log('Offline fixtures: all ranges, real client pagination and bucket filtering passed')
