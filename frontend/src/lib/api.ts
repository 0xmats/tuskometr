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
  nextCursor: number | null
}

export type Stats = {
  summary: {
    today: number
    last24Hours: number
    last7Days: number
  }
  range: {
    from: string
    to: string
    total: number
  }
  buckets: Array<{ start: string; count: number }>
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

async function request<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers: { Accept: "application/json" } })
  if (!response.ok) {
    throw new Error(`API zwróciło ${response.status}`)
  }
  return response.json() as Promise<T>
}

export function fetchOccurrences(rangeStart: Date, cursor?: number): Promise<OccurrencePage> {
  const params = new URLSearchParams({ from: rangeStart.toISOString(), limit: "30" })
  if (cursor) params.set("cursor", String(cursor))
  return request(`/api/occurrences?${params}`)
}

export function fetchStats(rangeStart: Date, bucket: "hour" | "day"): Promise<Stats> {
  const params = new URLSearchParams({
    from: rangeStart.toISOString(),
    bucket,
  })
  return request(`/api/stats?${params}`)
}

export function fetchStatus(): Promise<PipelineStatus> {
  return request("/api/status")
}
