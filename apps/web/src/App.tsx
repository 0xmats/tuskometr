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
} from "@/lib/api"

const RANGE_OPTIONS = [
  { label: "24 godz.", days: 1 },
  { label: "7 dni", days: 7 },
  { label: "30 dni", days: 30 },
] as const

const chartConfig = {
  count: { label: "Wystąpienia", color: "#b9232e" },
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

function HighlightedQuote({ text }: { text: string }) {
  const parts = text.split(formsPattern)
  return (
    <p className="font-display text-lg leading-8 text-foreground/90 md:text-xl">
      {parts.map((part, index) =>
        normalizedForms.has(part.toLocaleLowerCase("pl-PL")) ? (
          <mark key={`${part}-${index}`} className="bg-primary/10 px-0.5 font-semibold text-primary">
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
    <Card className="border-t-0 px-5 first:pl-0">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardDescription>{label}</CardDescription>
          <Icon className="size-4 text-muted-foreground" />
        </div>
      </CardHeader>
      <CardContent>
        {value === undefined ? <Skeleton className="mb-2 h-9 w-20" /> : <p className="font-display text-5xl font-bold tracking-tight">{value}</p>}
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
  const momentUrl = sourceMomentUrl(item, timelineOrigin)
  return (
    <article className="group relative grid gap-3 border-b border-stone-200 py-5 last:border-0 md:grid-cols-[108px_1fr_auto] md:gap-5">
      <div>
        <p className="font-mono text-lg font-semibold tracking-tight">{formatTime(item.occurredAt)}</p>
        <p className="mt-1 text-xs capitalize text-muted-foreground">{formatDate(item.occurredAt)}</p>
      </div>
      <div className="min-w-0">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <Badge variant="secondary">{item.form}</Badge>
        </div>
        <HighlightedQuote text={item.quote} />
      </div>
      <div className="flex w-fit shrink-0 items-center gap-1">
        {momentUrl ? (
          <Button asChild size="sm">
            <a href={momentUrl} target="_blank" rel="noreferrer">
              <ExternalLink className="size-4" />
              Zobacz fragment
            </a>
          </Button>
        ) : (
          <Button asChild variant="outline" size="sm">
            <a href={item.sourceUrl} target="_blank" rel="noreferrer">
              <ExternalLink className="size-4" />
              Zobacz kanał
            </a>
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
  const occurrences = [...new Map(
    pages.flatMap((page) => page.occurrences.items)
      .map((item) => [item.id, item]),
  ).values()]
  const chartData =
    statsQuery.data?.buckets.map((item) => ({
      label: formatBucket(item.start, days),
      count: item.count,
    })) ?? []

  const hasMonthOfHistory = Boolean(dashboard?.stats.historyStartedAt &&
    Date.parse(dashboard.generatedAt) - Date.parse(dashboard.stats.historyStartedAt) >= 30 * 86_400_000)
  const availableRanges = RANGE_OPTIONS.filter((option) => option.days !== 30 || hasMonthOfHistory)
  useEffect(() => {
    if (days === 30 && dashboard && !hasMonthOfHistory) setDays(7)
  }, [days, dashboard, hasMonthOfHistory])


  return (
    <div className="min-h-screen">
      <header className="mx-auto max-w-[1280px] px-5 md:px-8">
        <div className="flex items-center justify-between gap-4 border-b border-stone-200 py-3 text-[11px] font-semibold uppercase tracking-[0.13em] text-muted-foreground">
          <span>Niezależny monitoring mediów</span>
          <a href="#about-project" className="shrink-0 hover:text-primary">O projekcie ↗</a>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-5 py-7 md:py-9">
          <div>
            <h1 className="font-display text-5xl font-bold tracking-[-0.06em] sm:text-7xl">Tuskometr<span className="text-primary">.</span></h1>
            <p className="mt-2 text-xs text-muted-foreground sm:text-sm">Polityka na antenie. Liczby, cytaty, kontekst.</p>
          </div>
          {status?.state === "live" && (
            <span className="flex items-center gap-3 text-xs font-bold tracking-[0.16em] text-primary" aria-label="Na żywo">
              <span className="relative flex size-2.5" aria-hidden="true">
                <span className="absolute inset-0 rounded-full bg-primary/40 motion-safe:animate-ping" />
                <span className="relative size-2.5 rounded-full bg-primary" />
              </span>
              LIVE
            </span>
          )}
        </div>
        <nav aria-label="Sekcje strony" className="flex flex-wrap gap-x-7 gap-y-3 border-t-2 border-b border-foreground py-3 text-xs font-bold uppercase tracking-widest">
          <a href="#overview" className="text-primary">Republika pod lupą</a>
          <a href="#analysis" className="hover:text-primary">W liczbach</a>
          <a href="#timeline" className="hover:text-primary">Z anteny</a>
        </nav>
      </header>

      <main className="mx-auto max-w-[1280px] px-5 py-8 md:px-8 md:py-10">
        <section id="overview" className="mb-8 flex flex-col justify-between gap-5 lg:flex-row lg:items-end">
          <div className="max-w-2xl">
            <p className="mb-4 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.16em] text-primary"><Radio className="size-3.5" /> Temat obserwacji · Donald Tusk</p>
            <h2 className="font-display text-4xl font-bold leading-[1.06] tracking-[-0.04em] md:text-6xl">
              Ile razy padło nazwisko <span className="text-primary">Tusk?</span>
            </h2>
            <p className="mt-4 max-w-xl text-sm leading-6 text-muted-foreground md:text-base">
              Jak często Telewizja Republika mówi o Tusku? Sprawdź liczby i zobacz, w jakim kontekście pada jego nazwisko.
            </p>
          </div>

        </section>

        {dataIsStale && (
          <p role="status" className="mb-4 text-sm text-amber-800">
            {refreshFailed
              ? "Nie możemy teraz odświeżyć wyników. Spróbuj ponownie za chwilę."
              : "Wyświetlamy ostatnie dostępne wyniki. Mogą być nieaktualne."}
          </p>
        )}
        <section className="grid divide-y divide-stone-200 border-y border-stone-300 sm:grid-cols-2 sm:divide-x sm:divide-y-0 xl:grid-cols-4">
          <div className="bg-primary px-5 py-5 text-white" aria-label="Tusków na godzinę">
            <p className="text-xs font-bold uppercase tracking-[0.12em]">Tusków na godzinę</p>
            <div className="my-2 flex items-baseline gap-2">
              <span className="font-display text-6xl font-bold tabular-nums">
                {statsQuery.data?.summary.lastHour?.toLocaleString("pl-PL") ?? "—"}
              </span>
              <span className="text-sm text-white/85">/ godz.</span>
            </div>
            <p className="text-xs text-white/90">Wzmianki z ostatnich 60 minut</p>
          </div>
          <StatCard label="Dzisiaj" value={statsQuery.data?.summary.today} detail="wystąpień nazwiska Tusk" icon={Clock3} />
          <StatCard label="Ostatnie 24 godziny" value={statsQuery.data?.summary.last24Hours} detail="wystąpień nazwiska Tusk" icon={Activity} />
          <StatCard label="Ostatnie 7 dni" value={statsQuery.data?.summary.last7Days} detail="wystąpień nazwiska Tusk" icon={BarChart3} />

        </section>

        <section id="analysis" className="mt-10 grid gap-8 xl:grid-cols-[minmax(0,1.45fr)_minmax(300px,0.55fr)]">
          <Card>
            <CardHeader className="flex-row flex-wrap items-start justify-between gap-x-5 gap-y-4">
              <div className="min-w-0 flex-1 basis-64">
                <CardTitle>Natężenie wystąpień</CardTitle>
                <CardDescription className="mt-1">Ile razy padło nazwisko Tusk w wybranym okresie</CardDescription>
              </div>
              <div className="ml-auto flex max-w-full flex-wrap items-center justify-end gap-3">
                <div role="group" aria-label="Zakres wykresu" className="flex gap-1">
                  {availableRanges.map((option) => (
                    <Button
                      key={option.days}
                      variant={days === option.days ? "default" : "ghost"}
                      size="sm"
                      aria-pressed={days === option.days}
                      onClick={() => setDays(option.days)}
                    >
                      {option.label}
                    </Button>
                  ))}
                </div>
                <Badge variant="secondary" className="w-24 gap-1 px-2 tabular-nums">
                  <span>łącznie</span>
                  <span>{statsQuery.data?.range.total?.toLocaleString("pl-PL") ?? "—"}</span>
                </Badge>
              </div>
            </CardHeader>
            <CardContent>
              {statsQuery.isLoading ? (
                <Skeleton className="h-[280px] w-full" />
              ) : chartData.length ? (
                <ChartContainer config={chartConfig} className="h-[280px] w-full">
                  <BarChart data={chartData} margin={{ left: -24, right: 8, top: 12 }}>
                    <CartesianGrid vertical={false} stroke="#e7e5e0" />
                    <XAxis dataKey="label" tickLine={false} axisLine={false} tickMargin={12} minTickGap={24} />
                    <YAxis allowDecimals={false} tickLine={false} axisLine={false} />
                    <ChartTooltip cursor={{ fill: "rgba(0,0,0,.04)" }} content={<ChartTooltipContent />} />
                    <Bar dataKey="count" fill="var(--color-count)" radius={[0, 0, 0, 0]} maxBarSize={34} />
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
                      <div className="h-1.5 overflow-hidden bg-stone-100">
                        <div className="h-full bg-primary" style={{ width: `${Math.max(5, (item.count / max) * 100)}%` }} />
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

        <section id="timeline" className="mt-10">
          <Card>
            <CardHeader className="border-b border-stone-200 md:flex-row md:items-center md:justify-between">
              <div>
                <CardTitle>Z anteny</CardTitle>
                <CardDescription className="mt-1">Najnowsze wzmianki o Tusku</CardDescription>
              </div>
              <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground md:mt-0">
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
                  <div className="mb-4 flex size-12 items-center justify-center rounded-2xl bg-stone-100 text-muted-foreground">
                    <SearchX className="size-5" />
                  </div>
                  <p className="font-medium">Brak wzmianek w tym okresie</p>
                  <p className="mt-1 text-sm text-muted-foreground">Nowe wyniki pojawią się tutaj automatycznie.</p>
                </div>
              )}
            </CardContent>
          </Card>
        </section>

        <footer className="mt-8 border-t-2 border-foreground py-8 text-xs leading-5 text-muted-foreground">
          <section aria-labelledby="about-project" className="max-w-3xl space-y-2">
            <h2 id="about-project" className="text-sm font-medium text-foreground">O projekcie</h2>
            <p>
              Tuskometr jest niezależnym projektem analizy przekazu medialnego. Pokazuje częstotliwość
              występowania nazwiska „Tusk” na antenie Telewizji Republika.
            </p>
            <p>
              Przy wzmiankach znajdziesz krótkie cytaty i odnośniki do źródła. Wyniki i cytaty mogą
              zawierać błędy lub pominięcia. Projekt nie jest powiązany z Telewizją Republika ani YouTube.
            </p>
            <p>Źródło: publiczna transmisja Telewizji Republika w YouTube.</p>
          </section>
        </footer>
      </main>
    </div>
  )
}

export default App
