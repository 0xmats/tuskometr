export function comparisonCaption(
  current: number | undefined,
  previous: number | null | undefined,
  period: string,
): string | undefined {
  if (current == null || previous == null) return undefined
  if (current === previous) return `Bez zmian ${period}`
  if (previous === 0) return undefined
  const percent = Math.abs((current - previous) / previous * 100)
  const value = percent < 0.1 ? '<0,1' : percent.toLocaleString('pl-PL', { maximumFractionDigits: 1 })
  return `${current > previous ? '↑' : '↓'} ${value}% ${period}`
}

export function dailyAverageCaption(average: number | null | undefined): string | undefined {
  if (average == null) return undefined
  return `Średnio ${average.toLocaleString('pl-PL', { maximumFractionDigits: 1 })} dziennie`
}

export function peakHourCaption(peak: { count: number; start: string; end: string } | null | undefined): string | undefined {
  if (!peak) return undefined
  const plural = new Intl.PluralRules('pl-PL').select(peak.count)
  const noun = plural === 'one' ? 'wzmianka' : plural === 'few' ? 'wzmianki' : 'wzmianek'
  const hour = (value: string) => new Intl.DateTimeFormat('pl-PL', {
    timeZone: 'Europe/Warsaw', hour: 'numeric', hourCycle: 'h23',
  }).format(new Date(value))
  return `Szczyt: ${peak.count.toLocaleString('pl-PL')} ${noun} (${hour(peak.start)}–${hour(peak.end)})`
}
