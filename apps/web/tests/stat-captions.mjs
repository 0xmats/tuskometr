import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'

const source = readFileSync(new URL('../src/lib/stat-captions.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
})
const { comparisonCaption, dailyAverageCaption } =
  await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
const period = 'względem poprzednich 24 godz.'
assert.equal(comparisonCaption(118, 100, period), `↑ 18% ${period}`)
assert.equal(comparisonCaption(88, 100, period), `↓ 12% ${period}`)
assert.equal(comparisonCaption(0, 100, period), `↓ 100% ${period}`)
assert.equal(comparisonCaption(0, 0, period), `Bez zmian ${period}`)
assert.equal(comparisonCaption(5, 0, period), undefined)
assert.equal(comparisonCaption(5, null, period), undefined)
assert.equal(comparisonCaption(5, undefined, period), undefined)
assert.equal(comparisonCaption(undefined, 5, period), undefined)
assert.equal(comparisonCaption(10001, 10000, period), `↑ <0,1% ${period}`)
assert.equal(dailyAverageCaption(320), 'Średnio 320 dziennie')
assert.equal(dailyAverageCaption(1 / 7), 'Średnio 0,1 dziennie')
assert.equal(dailyAverageCaption(0), 'Średnio 0 dziennie')
assert.equal(dailyAverageCaption(null), undefined)
assert.equal(dailyAverageCaption(undefined), undefined)
console.log('Stat captions: comparisons, zero baseline, missing data and daily average passed')
const { peakHourCaption } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
const peak = { count: 82, start: '2026-09-08T17:00:00Z', end: '2026-09-08T18:00:00Z' }
assert.equal(peakHourCaption(peak), 'Maksimum: 82 wzmianki (19:00–20:00)')
assert.equal(peakHourCaption({ ...peak, count: 1 }), 'Maksimum: 1 wzmianka (19:00–20:00)')
assert.equal(peakHourCaption({ ...peak, count: 12 }), 'Maksimum: 12 wzmianek (19:00–20:00)')
assert.equal(peakHourCaption(null), undefined)

assert.equal(peakHourCaption({ count: 10, start: '2026-09-08T20:11:00Z', end: '2026-09-08T21:11:00Z' }), 'Maksimum: 10 wzmianek (22:11–23:11)')
