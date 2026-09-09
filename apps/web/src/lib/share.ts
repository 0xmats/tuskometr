import type { Dashboard } from "./api"

export type ShareSnapshot = {
  generatedAt: string
  lastHour: number | null
  today: number
  demo: boolean
}

export function snapshotFromDashboard(dashboard: Dashboard, demo = false): ShareSnapshot {
  return { generatedAt: dashboard.generatedAt,
    lastHour: dashboard.stats.summary.lastHour ?? null,
    today: dashboard.stats.summary.today, demo }
}

export function shareUrl(): string {
  return `${window.location.origin}/`
}

export function snapshotDate(snapshot: ShareSnapshot): string {
  return new Intl.DateTimeFormat("pl-PL", { dateStyle: "medium", timeStyle: "medium",
    timeZone: "Europe/Warsaw" }).format(new Date(snapshot.generatedAt))
}

function mentionUnit(count: number): string {
  const plural = new Intl.PluralRules("pl-PL").select(count)
  return plural === "one" ? "wzmianka" : plural === "few" ? "wzmianki" : "wzmianek"
}

export function shareText(snapshot: ShareSnapshot): string {
  const count = snapshot.lastHour
  const result = count === null
    ? "Brak danych o wzmiankach z ostatnich 60 minut w Telewizji Republika."
    : `${count.toLocaleString("pl-PL")} ${mentionUnit(count)} o Tusku w ostatnich 60 minutach w Telewizji Republika.`
  const date = new Intl.DateTimeFormat("pl-PL", {
    dateStyle: "medium", timeStyle: "short", timeZone: "Europe/Warsaw",
  }).format(new Date(snapshot.generatedAt))
  return `${snapshot.demo ? "DANE DEMONSTRACYJNE\n" : ""}${result}\nDzisiaj: ${snapshot.today.toLocaleString("pl-PL")}.\nStan na ${date} (czas polski).`
}

export function snapshotAlt(snapshot: ShareSnapshot): string {
  const result = snapshot.lastHour === null ? "brak danych" : `${snapshot.lastHour} ${mentionUnit(snapshot.lastHour)}`
  return `Tuskometr: ${result} o Tusku w ostatniej godzinie w Telewizji Republika, ${snapshot.today} dzisiaj. Stan na ${snapshotDate(snapshot)} (czas polski).${snapshot.demo ? " Dane demonstracyjne." : ""}`
}

export async function renderShareCard(snapshot: ShareSnapshot): Promise<Blob> {
  await document.fonts.ready
  const canvas = document.createElement("canvas")
  // Draw at export resolution so text stays crisp on high-density screens.
  const scale = 3
  canvas.width = 640 * scale
  canvas.height = 240 * scale
  const ctx = canvas.getContext("2d")
  if (!ctx) throw new Error("Nie można utworzyć obrazka")
  ctx.scale(scale, scale)
  ctx.fillStyle = "#ffffff"
  ctx.fillRect(0, 0, 640, 240)
  ctx.textBaseline = "top"
  function text(x: number, y: number, value: string, size: number,
    color = "#192128", weight = 400, width = 600, tracking = 0) {
    ctx!.fillStyle = color
    ctx!.letterSpacing = `${tracking}px`
    do {
      ctx!.font = `${weight} ${size}px "Geist Variable", sans-serif`
      size--
    } while (ctx!.measureText(value).width > width && size > 12)
    ctx!.fillText(value, x, y)
    return ctx!.measureText(value).width
  }
  const number = (value: number | null) => value === null ? "—" : value.toLocaleString("pl-PL")

  const logoWidth = text(20, 18, "Tuskometr", 28, undefined, 600, 240, -1.82)
  text(20 + logoWidth, 18, ".", 28, "#b04338", 600, 20, -1.82)
  ctx.textAlign = "right"
  text(620, 28, "Kanał Republika", 14, "#616a73", 400, 220)
  ctx.textAlign = "left"

  // Match the dashboard's adjoining red and light statistic tiles.
  ctx.save()
  ctx.beginPath()
  ctx.roundRect(20, 64, 600, 136, 12)
  ctx.clip()
  ctx.fillStyle = "#fbfcfd"
  ctx.fillRect(20, 64, 600, 136)
  ctx.fillStyle = "#b04338"
  ctx.fillRect(20, 64, 300, 136)
  ctx.restore()
  ctx.strokeStyle = "#e2e8f0"
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.roundRect(20.5, 64.5, 599, 135, 11.5)
  ctx.stroke()

  const labelWidth = text(38, 81, "Tusków", 18, "#ffffff", 700, 250)
  text(38 + labelWidth, 81, " na godzinę", 18, "#ffffff", 400, 180)
  const countWidth = text(35, 105, number(snapshot.lastHour), 62, "#ffffff", 600, 214, -3.1)
  text(35 + countWidth + 9, 143, "/ godz.", 13, "#f3dfdc", 400, 60)
  text(38, 177, "ostatnie 60 minut", 12, "#f3dfdc", 400, 250)

  text(340, 81, "Dzisiaj", 18, "#616a73", 400, 230)
  text(337, 105, number(snapshot.today), 62, undefined, 600, 265, -3.1)
  text(340, 177, `${mentionUnit(snapshot.today)} o Tusku`, 12, "#616a73", 400, 260)
  // Small clock, as on the dashboard's today tile.
  ctx.strokeStyle = "#616a73"
  ctx.lineWidth = 1.4
  ctx.lineCap = "round"
  ctx.lineJoin = "round"
  ctx.beginPath()
  ctx.arc(594, 90, 7, 0, Math.PI * 2)
  ctx.stroke()
  ctx.beginPath()
  ctx.moveTo(594, 85.5)
  ctx.lineTo(594, 90)
  ctx.lineTo(597, 91.5)
  ctx.stroke()

  const date = new Intl.DateTimeFormat("pl-PL", {
    dateStyle: "short", timeStyle: "short", timeZone: "Europe/Warsaw",
  }).format(new Date(snapshot.generatedAt))
  text(20, 218, "tuskometr.com", 12, "#b04338", 500, 180)
  if (snapshot.demo) text(166, 219, "Dane demonstracyjne", 10, "#616a73", 400, 155)
  ctx.textAlign = "right"
  text(620, 218, `Stan na ${date}`, 11, "#616a73", 400, 285)
  return new Promise((resolve, reject) => canvas.toBlob(
    blob => blob ? resolve(blob) : reject(new Error("Nie można utworzyć PNG")), "image/png"))
}
