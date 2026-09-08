import type { Dashboard } from "./api"

export type ShareSnapshot = {
  generatedAt: string
  lastHour: number | null
  today: number
  last24Hours: number
  demo: boolean
}

export function snapshotFromDashboard(dashboard: Dashboard, demo = false): ShareSnapshot {
  return { generatedAt: dashboard.generatedAt,
    lastHour: dashboard.stats.summary.lastHour ?? null,
    today: dashboard.stats.summary.today, last24Hours: dashboard.stats.summary.last24Hours, demo }
}

export function shareUrl(): string {
  return `${window.location.origin}/`
}

export function snapshotDate(snapshot: ShareSnapshot): string {
  return new Intl.DateTimeFormat("pl-PL", { dateStyle: "medium", timeStyle: "medium",
    timeZone: "Europe/Warsaw" }).format(new Date(snapshot.generatedAt))
}

export function snapshotAlt(snapshot: ShareSnapshot): string {
  return `Tuskometr: ${snapshot.lastHour ?? "brak danych"} wzmianek w ostatniej godzinie, ${snapshot.today} dzisiaj, ${snapshot.last24Hours} w ostatnich 24 godzinach. Stan na ${snapshotDate(snapshot)} (czas polski).${snapshot.demo ? " Dane demonstracyjne." : ""}`
}

export async function renderShareCard(snapshot: ShareSnapshot): Promise<Blob> {
  await document.fonts.ready
  const canvas = document.createElement("canvas")
  canvas.width = 1200
  canvas.height = 630
  const ctx = canvas.getContext("2d")
  if (!ctx) throw new Error("Nie można utworzyć obrazka")
  ctx.fillStyle = "#ffffff"
  ctx.fillRect(0, 0, 1200, 630)
  ctx.textBaseline = "top"
  function text(x: number, y: number, value: string, size: number, color = "#192128", bold = false, width = 1080) {
    ctx!.fillStyle = color
    do {
      ctx!.font = `${bold ? 650 : 400} ${size}px "Geist Variable", sans-serif`
      size--
    } while (ctx!.measureText(value).width > width && size > 12)
    ctx!.fillText(value, x, y)
  }
  const number = (value: number | null) => value === null ? "—" : value.toLocaleString("pl-PL")
  text(60, 40, "Tuskometr.", 52, undefined, true)
  text(60, 110, `Wzmianki o Donaldzie Tusku w Republika TV${snapshot.demo ? " · DEMO" : ""}`, 25)
  ctx.fillStyle = "#b04338"
  ctx.beginPath()
  ctx.roundRect(60, 163, 1080, 224, 18)
  ctx.fill()
  text(90, 188, "TUSKÓW NA GODZINĘ", 22, "white", true)
  text(85, 225, number(snapshot.lastHour), 112, "white", true, 1010)
  text(90, 350, "w ostatnich 60 minutach", 20, "white")
  text(60, 418, "Dzisiaj", 23, "#616a73")
  text(620, 418, "Ostatnie 24 godziny", 23, "#616a73")
  text(60, 456, number(snapshot.today), 49, undefined, true, 510)
  text(620, 456, number(snapshot.last24Hours), 49, undefined, true, 510)
  ctx.fillStyle = "#e1e4e7"
  ctx.fillRect(60, 528, 1080, 2)
  text(60, 550, `Stan na ${snapshotDate(snapshot)} (czas polski)`, 20, undefined, false, 790)
  text(880, 550, "tuskometr.com", 20, "#b04338", false, 260)
  text(60, 590, snapshot.demo ? "Dane demonstracyjne" : "Automatyczne zliczanie · transkrypcje mogą zawierać błędy", 17, "#616a73")
  return new Promise((resolve, reject) => canvas.toBlob(
    blob => blob ? resolve(blob) : reject(new Error("Nie można utworzyć PNG")), "image/png"))
}
