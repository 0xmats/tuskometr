import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'

const source = readFileSync(new URL('../src/lib/share.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
})
const { shareUrl, shareText, snapshotFromDashboard, snapshotDate } =
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
assert.match(shareText(captured), /^0 wzmianek o Tusku w ostatnich 60 minutach w Telewizji Republika\./)
assert.match(shareText(captured), /2 sty 2026, 00:30 \(czas polski\)/)
assert.match(shareText({ ...captured, generatedAt: '2026-07-01T23:30:00Z' }), /2 lip 2026, 01:30/)
for (const [count, unit] of [[1, 'wzmianka'], [2, 'wzmianki'], [5, 'wzmianek'], [12, 'wzmianek'], [22, 'wzmianki'], [101, 'wzmianek']]) {
  assert.ok(shareText({ ...captured, lastHour: count }).startsWith(`${count} ${unit} o Tusku`))
}
assert.match(shareText({ ...captured, lastHour: null }), /^Brak danych/)
assert.match(shareText({ ...captured, demo: true }), /^DANE DEMONSTRACYJNE\n/)
console.log('Sharing: immutable capture, Polish plurals, zero/missing counts, demo labels, timezone and clean link passed')
