import { useEffect, useRef, useState } from "react"
import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query"
import {
  Activity,
  ArrowUpRight,
  BarChart3,
  Clock3,
  ExternalLink,
  Radio,
  RefreshCw,
  SearchX,
  Signal,
} from "lucide-react"
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart"
import { Skeleton } from "@/components/ui/skeleton"
import { useYouTubeTimelineOrigin } from "@/hooks/use-youtube-timeline"
import {
  fetchDashboard,
  fetchManifest,
  dashboardIsStale,
  type Occurrence,
  type Dashboard,
  type PipelineStatus,
} from "@/lib/api"
import { cn } from "@/lib/utils"

const RANGE_OPTIONS = [
  { label: "24 godz.", days: 1 },
  { label: "7 dni", days: 7 },
  { label: "30 dni", days: 30 },
] as const

const chartConfig = {
  count: { label: "Wystąpienia", color: "#ef4e45" },
} satisfies ChartConfig

const formsPattern = /\b(tusk|tuska|tuskowi|tuskiem|tusku|tuskowie|tusków|tuskom|tuskami|tuskach)\b/giu
const normalizedForms = new Set(["tusk", "tuska", "tuskowi", "tuskiem", "tusku", "tuskowie", "tusków", "tuskom", "tuskami", "tuskach"])
const SOURCE_VIDEO_ID = "dzntyCTgJMQ"
const YOUTUBE_DVR_SECONDS = 12 * 60 * 60
const LINK_PREROLL_SECONDS = 3


function formatTime(value: string) {
  return new Intl.DateTimeFormat("pl-PL", {
    timeZone: "Europe/Warsaw",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value))
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("pl-PL", {
    timeZone: "Europe/Warsaw",
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(new Date(value))
}

function formatBucket(value: string, days: number) {
  return new Intl.DateTimeFormat("pl-PL", {
    timeZone: "Europe/Warsaw",
    day: days > 1 ? "2-digit" : undefined,
    month: days > 1 ? "2-digit" : undefined,
    hour: days <= 7 ? "2-digit" : undefined,
  }).format(new Date(value))
}

function statusPresentation(status?: PipelineStatus) {
  if (status?.state === "live") {
    return { label: "Transmisja aktywna", variant: "live" as const, dot: "bg-emerald-400" }
  }
  if (status?.state === "reconnecting" || status?.state === "starting") {
    return { label: "Łączenie ze źródłem", variant: "warning" as const, dot: "bg-amber-400" }
  }
  return { label: "Transmisja offline", variant: "offline" as const, dot: "bg-red-400" }
}

function HighlightedQuote({ text }: { text: string }) {
  const parts = text.split(formsPattern)
  return (
    <p className="text-[15px] leading-7 text-foreground/90">
      {parts.map((part, index) =>
        normalizedForms.has(part.toLocaleLowerCase("pl-PL")) ? (
          <mark key={`${part}-${index}`} className="rounded bg-primary/15 px-1 py-0.5 font-semibold text-primary">
            {part}
          </mark>
        ) : (
          part
        ),
      )}
    </p>
  )
}

function StatCard({
  label,
  value,
  detail,
  icon: Icon,
}: {
  label: string
  value?: number
  detail: string
  icon: typeof Activity
}) {
  return (
    <Card className="relative overflow-hidden">
      <div className="absolute right-0 top-0 h-24 w-24 translate-x-8 -translate-y-8 rounded-full bg-primary/[0.07] blur-2xl" />
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardDescription>{label}</CardDescription>
          <Icon className="size-4 text-muted-foreground" />
        </div>
      </CardHeader>
      <CardContent>
        {value === undefined ? <Skeleton className="mb-2 h-9 w-20" /> : <p className="font-display text-4xl font-semibold tracking-tight">{value}</p>}
        <p className="mt-2 text-xs text-muted-foreground">{detail}</p>
      </CardContent>
    </Card>
  )
}

function sourceMomentUrl(item: Occurrence, timelineOrigin: number | null) {
  if (timelineOrigin === null) return null
  const occurrenceSeconds = Date.parse(item.occurredAt) / 1_000
  const ageSeconds = Date.now() / 1_000 - occurrenceSeconds
  const position = Math.floor(occurrenceSeconds - timelineOrigin - LINK_PREROLL_SECONDS)
  if (!Number.isFinite(position) || position < 0 || ageSeconds > YOUTUBE_DVR_SECONDS) return null

  const url = new URL(item.sourceUrl)
  url.searchParams.set("t", `${position}s`)
  return url.toString()
}

function TimelineItem({ item, timelineOrigin }: { item: Occurrence; timelineOrigin: number | null }) {
  const confidence = Math.round(item.confidence * 100)
  const momentUrl = sourceMomentUrl(item, timelineOrigin)
  return (
    <article className="group relative grid gap-3 border-b border-white/[0.06] py-5 last:border-0 md:grid-cols-[108px_1fr_auto] md:gap-5">
      <div>
        <p className="font-mono text-lg font-semibold tracking-tight">{formatTime(item.occurredAt)}</p>
        <p className="mt-1 text-xs capitalize text-muted-foreground">{formatDate(item.occurredAt)}</p>
      </div>
      <div className="min-w-0">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <Badge variant="secondary">{item.form}</Badge>
          <span className="text-xs text-muted-foreground">pewność {confidence}%</span>
        </div>
        <HighlightedQuote text={item.quote} />
      </div>
      <div className="flex w-fit shrink-0 items-center gap-1">
        {momentUrl ? (
          <Button asChild size="sm">
            <a href={momentUrl} target="_blank" rel="noreferrer">
              <ExternalLink className="size-4" />
              Otwórz moment
            </a>
          </Button>
        ) : (
          <Button
            size="sm"
            disabled
            title={timelineOrigin === null ? "Kalibracja osi czasu YouTube" : "Moment wypadł poza okno DVR YouTube"}
          >
            <ExternalLink className="size-4" />
            {timelineOrigin === null ? "Ustalam moment…" : "Poza oknem DVR"}
          </Button>
        )}
      </div>
    </article>
  )
}

function App() {
  const [days, setDays] = useState(7)
  const [now, setNow] = useState(() => performance.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(performance.now()), 15_000)
    return () => window.clearInterval(timer)
  }, [])
  const manifestQuery = useQuery({
    queryKey: ["manifest"],
    queryFn: fetchManifest,
    refetchInterval: 15_000,
    staleTime: 5_000,
    refetchOnWindowFocus: true,
  })
  const manifest = manifestQuery.data
  const timelineOrigin = useYouTubeTimelineOrigin(SOURCE_VIDEO_ID)
  const occurrencesQuery = useInfiniteQuery({
    queryKey: ["dashboard", days, manifest?.version],
    queryFn: ({ pageParam }) => fetchDashboard(pageParam),
    initialPageParam: manifest?.dashboards[String(days)] ?? "",
    getNextPageParam: (page) => page.occurrences.nextPage ?? undefined,
    enabled: Boolean(manifest?.dashboards[String(days)]),
    placeholderData: keepPreviousData,
    refetchOnWindowFocus: false,
    staleTime: Infinity,
    gcTime: 60_000,
  })

  const lastGoodPages = useRef<Dashboard[]>([])
  useEffect(() => {
    if (occurrencesQuery.data && !occurrencesQuery.isPlaceholderData) {
      lastGoodPages.current = occurrencesQuery.data.pages
    }
  }, [occurrencesQuery.data, occurrencesQuery.isPlaceholderData])
  const pages = occurrencesQuery.data?.pages ?? lastGoodPages.current
  const dashboard = pages[0]
  const statsQuery = {
    ...occurrencesQuery, data: dashboard?.stats,
    isLoading: !dashboard && (manifestQuery.isPending || occurrencesQuery.isPending),
  }
  const refreshFailed = manifestQuery.isError || occurrencesQuery.isError
  const snapshotExpired = dashboard != null && manifest != null &&
    dashboardIsStale(dashboard, manifest, now)
  const dataIsStale = refreshFailed || snapshotExpired
  const status = dataIsStale ? undefined : dashboard?.status
  const statusView = statusPresentation(status)
  const occurrences = [...new Map(
    pages.flatMap((page) => page.occurrences.items)
      .map((item) => [item.id, item]),
  ).values()]
  const chartData =
    statsQuery.data?.buckets.map((item) => ({
      label: formatBucket(item.start, days),
      count: item.count,
    })) ?? []

  const refresh = () => {
    void manifestQuery.refetch()
    if (occurrencesQuery.isError) void occurrencesQuery.refetch()
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-white/[0.06] bg-background/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1400px] items-center justify-between px-5 py-5 md:px-8">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
              <Signal className="size-5" />
            </div>
            <div>
              <h1 className="font-display text-xl font-semibold tracking-[-0.03em]">tuskometr</h1>
              <p className="text-xs text-muted-foreground">monitoring transmisji na żywo</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={statusView.variant} className="hidden sm:inline-flex">
              <span className={cn("size-1.5 rounded-full", statusView.dot, status?.state === "live" && "animate-pulse")} />
              {statusView.label}
            </Badge>
            <Button variant="outline" size="icon" onClick={refresh} aria-label="Odśwież dane">
              <RefreshCw className={cn("size-4", statsQuery.isFetching && "animate-spin")} />
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1400px] px-5 py-8 md:px-8 md:py-10">
        <section className="mb-8 flex flex-col justify-between gap-5 lg:flex-row lg:items-end">
          <div className="max-w-2xl">
            <Badge variant="secondary" className="mb-4"><Radio className="size-3" /> Automatyczna transkrypcja</Badge>
            <h2 className="font-display text-3xl font-semibold tracking-[-0.04em] md:text-5xl">
              Ile razy padło nazwisko <span className="text-primary">Tusk?</span>
            </h2>
            <p className="mt-4 max-w-xl text-sm leading-6 text-muted-foreground md:text-base">
              Wykryte odmiany nazwiska w transmisji Telewizji Republika. Statystyki odświeżamy co 30 sekund; transkrypcja wprowadza dodatkowe opóźnienie.
            </p>
          </div>
          <div className="flex w-fit rounded-xl border border-white/[0.08] bg-white/[0.03] p-1">
            {RANGE_OPTIONS.map((option) => (
              <Button
                key={option.days}
                variant={days === option.days ? "default" : "ghost"}
                size="sm"
                onClick={() => setDays(option.days)}
              >
                {option.label}
              </Button>
            ))}
          </div>
        </section>

        {dataIsStale && (
          <p role="status" className="mb-4 text-sm text-amber-400">
            {refreshFailed
              ? "Nie udało się pobrać nowych danych. Wyświetlamy ostatnie dostępne statystyki."
              : "Generator nie opublikował świeżych danych. Wyświetlane statystyki mogą być nieaktualne."}
          </p>
        )}
        <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard label="Dzisiaj" value={statsQuery.data?.summary.today} detail="od północy czasu polskiego" icon={Clock3} />
          <StatCard label="Ostatnie 24 godziny" value={statsQuery.data?.summary.last24Hours} detail="ruchome okno dobowe" icon={Activity} />
          <StatCard label="Ostatnie 7 dni" value={statsQuery.data?.summary.last7Days} detail="wszystkie rozpoznane odmiany" icon={BarChart3} />
          <StatCard
            label="Opóźnienie pipeline’u"
            value={status?.lagSeconds == null ? undefined : Math.round(status.lagSeconds)}
            detail={status?.modelName ? `sekundy · model ${status.modelName}` : "sekundy od transmisji"}
            icon={Signal}
          />
        </section>

        <section className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1.45fr)_minmax(300px,0.55fr)]">
          <Card>
            <CardHeader className="flex-row items-center justify-between">
              <div>
                <CardTitle>Natężenie wystąpień</CardTitle>
                <CardDescription className="mt-1">Liczba wykryć w wybranym okresie</CardDescription>
              </div>
              <Badge variant="secondary">łącznie {statsQuery.data?.range.total ?? "—"}</Badge>
            </CardHeader>
            <CardContent>
              {statsQuery.isLoading ? (
                <Skeleton className="h-[280px] w-full" />
              ) : chartData.length ? (
                <ChartContainer config={chartConfig} className="h-[280px] w-full">
                  <BarChart data={chartData} margin={{ left: -24, right: 8, top: 12 }}>
                    <CartesianGrid vertical={false} stroke="rgba(255,255,255,.06)" />
                    <XAxis dataKey="label" tickLine={false} axisLine={false} tickMargin={12} minTickGap={24} />
                    <YAxis allowDecimals={false} tickLine={false} axisLine={false} />
                    <ChartTooltip cursor={{ fill: "rgba(255,255,255,.04)" }} content={<ChartTooltipContent />} />
                    <Bar dataKey="count" fill="var(--color-count)" radius={[5, 5, 2, 2]} maxBarSize={34} />
                  </BarChart>
                </ChartContainer>
              ) : (
                <div className="flex h-[280px] flex-col items-center justify-center text-center text-muted-foreground">
                  <SearchX className="mb-3 size-7" />
                  <p className="text-sm">Brak wystąpień w tym okresie</p>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Najczęstsze formy</CardTitle>
              <CardDescription>Rozkład odmian nazwiska</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {statsQuery.isLoading ? (
                Array.from({ length: 5 }).map((_, index) => <Skeleton key={index} className="h-8 w-full" />)
              ) : statsQuery.data?.forms.length ? (
                statsQuery.data.forms.slice(0, 7).map((item) => {
                  const max = statsQuery.data?.forms[0]?.count || 1
                  return (
                    <div key={item.form}>
                      <div className="mb-1.5 flex items-center justify-between text-sm">
                        <span className="font-medium">{item.form}</span>
                        <span className="font-mono text-muted-foreground">{item.count}</span>
                      </div>
                      <div className="h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
                        <div className="h-full rounded-full bg-primary" style={{ width: `${Math.max(5, (item.count / max) * 100)}%` }} />
                      </div>
                    </div>
                  )
                })
              ) : (
                <p className="py-20 text-center text-sm text-muted-foreground">Jeszcze brak danych</p>
              )}
            </CardContent>
          </Card>
        </section>

        <section className="mt-6">
          <Card>
            <CardHeader className="border-b border-white/[0.06] md:flex-row md:items-center md:justify-between">
              <div>
                <CardTitle>Oś czasu</CardTitle>
                <CardDescription className="mt-1">Najnowsze wykryte wystąpienia wraz z kontekstem</CardDescription>
              </div>
              <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground md:mt-0">
                <span className={cn("size-2 rounded-full", statusView.dot)} />
                Ostatnia aktualizacja {status?.updatedAt ? formatTime(status.updatedAt) : "—"}
              </div>
            </CardHeader>
            <CardContent>
              {statsQuery.isLoading ? (
                <div className="space-y-4 py-5">
                  {Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-24 w-full" />)}
                </div>
              ) : occurrences.length ? (
                <>
                  {occurrences.map((item) => <TimelineItem key={item.id} item={item} timelineOrigin={timelineOrigin} />)}
                  {occurrencesQuery.hasNextPage && (
                    <div className="flex justify-center pt-5">
                      <Button
                        variant="outline"
                        onClick={() => occurrencesQuery.fetchNextPage()}
                        disabled={occurrencesQuery.isFetchingNextPage || occurrencesQuery.isPlaceholderData}
                      >
                        {occurrencesQuery.isFetchingNextPage ? <RefreshCw className="size-4 animate-spin" /> : <ArrowUpRight className="size-4" />}
                        Pokaż starsze
                      </Button>
                    </div>
                  )}
                </>
              ) : (
                <div className="flex min-h-56 flex-col items-center justify-center text-center">
                  <div className="mb-4 flex size-12 items-center justify-center rounded-2xl bg-white/[0.04] text-muted-foreground">
                    <SearchX className="size-5" />
                  </div>
                  <p className="font-medium">Brak wykrytych wystąpień</p>
                  <p className="mt-1 text-sm text-muted-foreground">Nowe wyniki pojawią się tutaj automatycznie.</p>
                </div>
              )}
            </CardContent>
          </Card>
        </section>

        <footer className="py-8 text-xs leading-5 text-muted-foreground">
          <section aria-labelledby="about-project" className="max-w-3xl space-y-2">
            <h2 id="about-project" className="text-sm font-medium text-foreground">O projekcie</h2>
            <p>
              Tuskometr jest niezależnym projektem analizy przekazu medialnego. Pokazuje częstotliwość
              występowania nazwiska „Tusk” w monitorowanej transmisji Telewizji Republika.
            </p>
            <p>
              Krótkie fragmenty automatycznej transkrypcji ilustrują wykryte wystąpienia; odnośniki
              prowadzą do materiału źródłowego. Wyniki dotyczą przetworzonego materiału i mogą
              zawierać błędy lub luki. Projekt nie jest powiązany z Telewizją Republika ani YouTube.
            </p>
            <p>Źródło: publiczna transmisja Telewizji Republika w YouTube.</p>
          </section>
        </footer>
      </main>
    </div>
  )
}

export default App
