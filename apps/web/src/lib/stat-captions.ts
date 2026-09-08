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
