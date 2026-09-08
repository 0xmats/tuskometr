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
