export type Occurrence = {
  id: number
  occurredAt: string
  form: string
  quote: string
  confidence: number
  sourceUrl: string
  sourcePositionSeconds: number | null
}

export type OccurrencePage = {
  items: Occurrence[]
  nextPage: string | null
}

export type Stats = {
  historyStartedAt?: string | null
  summary: {
    lastHour?: number
    today: number
    last24Hours: number
    last7Days: number
  }
  range: {
    from: string
    to: string
    total: number
  }
  buckets: Array<{ start: string; end: string; count: number }>
  forms: Array<{ form: string; count: number }>
}

export type PipelineStatus = {
  state: "starting" | "live" | "reconnecting" | "offline" | string
  lastAudioAt: string | null
  lastTranscriptAt: string | null
  lagSeconds: number | null
  reconnectCount: number
  message: string | null
  modelName: string | null
  updatedAt: string
}

const dataOrigin = (import.meta.env.VITE_DATA_ORIGIN ?? "").replace(/\/$/, "")

function dataUrl(path: string): string {
  if (!path.startsWith("/dashboard/")) throw new Error("Nieprawidłowy adres danych")
  return `${dataOrigin}${path}`
}

async function request<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(dataUrl(url), { headers: { Accept: "application/json" }, signal })
  if (!response.ok) {
    throw new Error(`API zwróciło ${response.status}`)
  }
  return response.json() as Promise<T>
}

export type Dashboard = {
  historyPages?: string[]
  bucketPages?: Record<string, string[]>
  generatedAt: string
  stats: Stats
  status: PipelineStatus
  occurrences: OccurrencePage
}

export type Manifest = {
  version: string
  generatedAt: string
  staleAfterSeconds: number
  dashboards: Record<string, string>
  receivedAtMs: number
  serverTimeAtReceiptMs: number
}

export async function fetchManifest(): Promise<Manifest> {
  const response = await fetch(dataUrl("/dashboard/manifest.json"), {
    headers: { Accept: "application/json" },
    // Respect the manifest's short TTL in both the browser and the CDN.
    cache: "default",
  })
  if (!response.ok) throw new Error(`Manifest zwrócił ${response.status}`)
  const manifest = await response.json() as Manifest
  const serverDate = Date.parse(response.headers.get("Date") ?? "")
  const ageSeconds = Number(response.headers.get("Age") ?? 0)
  if (!Number.isFinite(serverDate) || !Number.isFinite(ageSeconds)) {
    throw new Error("Nie można ustalić czasu publikacji danych")
  }
  return {
    ...manifest,
    receivedAtMs: performance.now(),
    serverTimeAtReceiptMs: serverDate + Math.max(0, ageSeconds) * 1000,
  }
}

export function dashboardIsStale(dashboard: Dashboard, manifest: Manifest, nowMs: number): boolean {
  // Both timestamps use the server's clock; elapsed time is monotonic and does
  // not depend on the user's clock, time zone or clock corrections.
  const serverNow = manifest.serverTimeAtReceiptMs + Math.max(0, nowMs - manifest.receivedAtMs)
  return serverNow - Date.parse(dashboard.generatedAt) > manifest.staleAfterSeconds * 1000
}

export async function fetchDashboard(url: string, signal?: AbortSignal): Promise<Dashboard> {
  const [path, fragment] = url.split("#")
  const dashboard = await request<Dashboard>(path, signal)
  if (!dashboard.historyPages) return dashboard
  const parts = (fragment ?? "0").split(":")
  let page = Number(parts[0])
  let offset = parts.length === 2 ? Number(parts[1]) : 0
  if (parts.length > 2 || !Number.isInteger(page) || page < 0 ||
      page > dashboard.historyPages.length || !Number.isInteger(offset) || offset < 0) {
    throw new Error("Nieprawidłowa strona historii")
  }
  const items: Occurrence[] = []
  while (page <= dashboard.historyPages.length && items.length < 30) {
    const chunk = page === 0 ? dashboard.occurrences.items
      : (await request<{ items: Occurrence[] }>(dashboard.historyPages[page - 1], signal)).items
    if (offset > chunk.length) throw new Error("Nieprawidłowa strona historii")
    const selected = chunk.slice(offset, offset + 30 - items.length)
    items.push(...selected)
    offset += selected.length
    if (offset === chunk.length) {
      page += 1
      offset = 0
    }
  }
  return {
    ...dashboard,
    occurrences: {
      items,
      nextPage: page <= dashboard.historyPages.length ? `${path}#${page}:${offset}` : null,
    },
  }
}


export function sortOccurrences(items: Occurrence[]): Occurrence[] {
  return [...new Map(items.map((item) => [item.id, item])).values()]
    .sort((a, b) => Date.parse(b.occurredAt) - Date.parse(a.occurredAt) || b.id - a.id)
}

export function rangeAvailable(days: number, stats: Stats | undefined, generatedAt?: string): boolean {
  if (days < 7) return true
  if (!stats?.historyStartedAt || !generatedAt) return false
  const requiredDays = days === 7 ? 1 : 7
  return Date.parse(generatedAt) - Date.parse(stats.historyStartedAt) > requiredDays * 86_400_000
}

export async function fetchBucketOccurrences(
  dashboard: Dashboard, start: string, end: string, signal?: AbortSignal,
): Promise<Occurrence[]> {
  let items: Occurrence[]
  const urls = dashboard.bucketPages?.[start]
  if (urls) {
    items = []
    for (let offset = 0; offset < urls.length; offset += 4) {
      const pages = await Promise.all(urls.slice(offset, offset + 4)
        .map((url) => request<{ items: Occurrence[] }>(url, signal)))
      items.push(...pages.flatMap((page) => page.items))
    }
  } else {
    // Compatibility with snapshots published before the bucket index was introduced.
    items = [...dashboard.occurrences.items]
    let next = dashboard.occurrences.nextPage
    const visited = new Set<string>()
    while (next) {
      signal?.throwIfAborted()
      if (visited.has(next)) throw new Error("Nieprawidłowa paginacja historii")
      visited.add(next)
      const page = await fetchDashboard(next, signal)
      items.push(...page.occurrences.items)
      next = page.occurrences.nextPage
    }
  }
  const from = Date.parse(start)
  const to = Date.parse(end)
  return sortOccurrences(items.filter((item) => {
    const time = Date.parse(item.occurredAt)
    return time >= from && time < to
  }))
}
