import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'

const source = readFileSync(new URL('../src/lib/share.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
})
const { shareUrl, snapshotFromDashboard, snapshotDate } =
  await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
globalThis.window = { location: {
  origin: 'https://tuskometr.com', pathname: '/anything', search: '?tracking=123', hash: '#overview',
} }
assert.equal(shareUrl(), 'https://tuskometr.com/')
const dashboard = { generatedAt: '2026-01-01T23:30:00.000Z',
  stats: { summary: { lastHour: 0, today: 15, last24Hours: 321 } } }
const captured = snapshotFromDashboard(dashboard)
dashboard.stats.summary.today = 999
assert.equal(captured.today, 15)
assert.equal(captured.lastHour, 0)
assert.equal(snapshotFromDashboard({ ...dashboard, stats: { summary: {} } }).lastHour, null)
assert.equal(snapshotFromDashboard(dashboard, true).demo, true)
assert.match(snapshotDate(captured), /2 sty 2026/)
console.log('Share card: immutable capture, zero/missing counts, timezone and clean live-site link passed')
