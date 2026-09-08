import { createHash } from "node:crypto"
import { readFileSync } from "node:fs"
import type { Plugin } from "vite"

type Fixture = {
  historyDays: number
  staleAfterSeconds: number
  status: { state: string; lagSeconds: number; reconnectCount: number; message: string | null }
  occurrences: Array<{
    id: number; minutesAgo: number; form: string; quote: string; confidence: number
  }>
}

export function buildMockDashboard(fixture: Fixture, now = Date.now()) {
  const iso = (value: number) => new Date(value).toISOString()
  const generatedAt = iso(now)
  const version = createHash("sha256").update(JSON.stringify(fixture) + generatedAt).digest("hex")
  const prefix = `/dashboard/mock/${version}`
  const routes = new Map<string, unknown>()
  const all = fixture.occurrences.map(({ minutesAgo, ...item }) => ({
    ...item, occurredAt: iso(now - minutesAgo * 60_000), sourceUrl: "",
    sourcePositionSeconds: null,
  })).sort((a, b) => b.occurredAt.localeCompare(a.occurredAt) || b.id - a.id)
  const within = (duration: number) => all.filter(item => Date.parse(item.occurredAt) >= now - duration)
  const day = 86_400_000
  const polishDate = (value: number) => new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Warsaw", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date(value))
  const summary = {
    lastHour: within(3_600_000).length,
    today: all.filter(item => polishDate(Date.parse(item.occurredAt)) === polishDate(now)).length,
    last24Hours: within(day).length,
    last7Days: within(7 * day).length,
    dailyAverage: fixture.historyDays >= 1 ? within(7 * day).length / Math.min(7, fixture.historyDays) : null,
  }
  const ascending = [...all].reverse().filter(item => Date.parse(item.occurredAt) <= now)
  let hourlyRecord: { count: number; start: string; end: string } | null = null
  let left = 0
  for (let right = 0; right < ascending.length; right++) {
    const end = Date.parse(ascending[right].occurredAt)
    while (Date.parse(ascending[left].occurredAt) < end - 3_600_000) left++
    const count = right - left + 1
    if (!hourlyRecord || count > hourlyRecord.count) {
      hourlyRecord = { count, start: iso(end - 3_600_000), end: iso(end) }
    }
  }
  const recordItems = all.filter(item => hourlyRecord &&
    item.occurredAt >= hourlyRecord.start && item.occurredAt <= hourlyRecord.end)
  const recordPages = []
  for (let offset = 0; offset < recordItems.length; offset += 30) {
    const url = `${prefix}/record-${offset}.json`
    routes.set(url, { items: recordItems.slice(offset, offset + 30) })
    recordPages.push(url)
  }
  const dashboards: Record<string, string> = {}
  for (const days of [0, 1, 7, 30]) {
    const duration = days === 0 ? 3_600_000 : days * day
    const step = days === 0 ? 60_000 : days === 1 ? 3_600_000 : day
    const selected = within(duration)
    const buckets = []
    const bucketPages: Record<string, string[]> = {}
    for (let start = Math.floor((now - duration) / step) * step; start <= now; start += step) {
      const items = selected.filter(item => {
        const at = Date.parse(item.occurredAt)
        return at >= start && at < start + step
      })
      const url = `${prefix}/${days}-bucket-${start}.json`
      routes.set(url, { items })
      bucketPages[iso(start)] = items.length ? [url] : []
      buckets.push({ start: iso(start), end: iso(start + step), count: items.length })
    }
    const historyPages = []
    for (let offset = 30; offset < selected.length; offset += 30) {
      const url = `${prefix}/${days}-page-${offset}.json`
      historyPages.push(url)
      routes.set(url, { items: selected.slice(offset, offset + 30) })
    }
    const forms = new Map<string, number>()
    for (const item of selected) forms.set(item.form, (forms.get(item.form) ?? 0) + 1)
    const url = `${prefix}/${days}.json`
    dashboards[String(days)] = url
    routes.set(url, {
      generatedAt, historyPages, bucketPages, recordPages,
      stats: {
        historyStartedAt: iso(now - fixture.historyDays * day), summary, hourlyRecord,
        range: { from: iso(now - duration), to: generatedAt, total: selected.length },
        buckets, forms: [...forms].map(([form, count]) => ({ form, count })),
      },
      status: {
        ...fixture.status, updatedAt: generatedAt,
        lastAudioAt: generatedAt, lastTranscriptAt: generatedAt,
      },
      occurrences: { items: selected.slice(0, 30), nextPage: null },
    })
  }
  routes.set("/dashboard/manifest.json", {
    version, generatedAt, staleAfterSeconds: fixture.staleAfterSeconds, dashboards,
  })
  return routes
}

export function mockDashboard(fixturePath: string): Plugin {
  return {
    name: "local-dashboard-fixture",
    apply: "serve",
    configureServer(server) {
      const read = () => buildMockDashboard(JSON.parse(readFileSync(fixturePath, "utf8")))
      let routes = read()
      server.watcher.add(fixturePath)
      server.watcher.on("change", (file) => {
        if (file !== fixturePath) return
        try {
          routes = read()
          server.ws.send({ type: "full-reload" })
        } catch (error) {
          server.config.logger.error(`Invalid dashboard fixture: ${String(error)}`)
        }
      })
      server.middlewares.use((request, response, next) => {
        const pathname = (request.url ?? "").split("?")[0]
        if (!pathname.startsWith("/dashboard/")) return next()
        const data = routes.get(pathname)
        response.statusCode = data ? 200 : 404
        response.setHeader("Content-Type", "application/json; charset=utf-8")
        response.setHeader("Cache-Control", "no-store")
        response.setHeader("Date", new Date().toUTCString())
        response.end(JSON.stringify(data ?? { error: "Unknown fixture path" }))
      })
    },
  }
}
