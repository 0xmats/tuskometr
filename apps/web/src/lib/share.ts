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
  canvas.width = 360 * scale
  canvas.height = 480 * scale
  const ctx = canvas.getContext("2d")
  if (!ctx) throw new Error("Nie można utworzyć obrazka")
  ctx.scale(scale, scale)
  ctx.fillStyle = "#ffffff"
  ctx.fillRect(0, 0, 360, 480)
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

  const logoWidth = text(24, 22, "Tuskometr", 30, undefined, 600, 260, -1.82)
  text(24 + logoWidth, 22, ".", 30, "#b04338", 600, 20, -1.82)
  text(24, 59, "Monitorujemy wzmianki o Tusku w Republice", 14, "#616a73", 400, 312)

  // Stack the dashboard's red and light statistic tiles for phone screens.
  ctx.save()
  ctx.beginPath()
  ctx.roundRect(24, 96, 312, 288, 12)
  ctx.clip()
  ctx.fillStyle = "#fbfcfd"
  ctx.fillRect(24, 96, 312, 288)
  ctx.fillStyle = "#b04338"
  ctx.fillRect(24, 96, 312, 152)
  ctx.restore()
  ctx.strokeStyle = "#e2e8f0"
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.roundRect(24.5, 96.5, 311, 287, 11.5)
  ctx.stroke()

  const labelWidth = text(44, 114, "Tusków", 18, "#ffffff", 700, 250)
  text(44 + labelWidth, 114, " na godzinę", 18, "#ffffff", 400, 180)
  const countWidth = text(41, 140, number(snapshot.lastHour), 68, "#ffffff", 600, 205, -3.1)
  text(41 + countWidth + 9, 182, "/ godz.", 14, "#f3dfdc", 400, 60)
  text(44, 223, "ostatnie 60 minut", 13, "#f3dfdc", 400, 250)

  text(44, 264, "Dzisiaj", 18, "#616a73", 400, 230)
  text(41, 290, number(snapshot.today), 62, undefined, 600, 270, -3.1)
  text(44, 359, `${mentionUnit(snapshot.today)} o Tusku`, 13, "#616a73", 400, 260)
  // Small clock, as on the dashboard's today tile.
  ctx.strokeStyle = "#616a73"
  ctx.lineWidth = 1.4
  ctx.lineCap = "round"
  ctx.lineJoin = "round"
  ctx.beginPath()
  ctx.arc(308, 273, 7, 0, Math.PI * 2)
  ctx.stroke()
  ctx.beginPath()
  ctx.moveTo(308, 268.5)
  ctx.lineTo(308, 273)
  ctx.lineTo(311, 274.5)
  ctx.stroke()

  const date = new Intl.DateTimeFormat("pl-PL", {
    dateStyle: "short", timeStyle: "short", timeZone: "Europe/Warsaw",
  }).format(new Date(snapshot.generatedAt))
  ctx.textAlign = "center"
  text(180, 398, `Stan na ${date}`, 12, "#616a73", 400, 312)
  if (snapshot.demo) text(180, 418, "Dane demonstracyjne", 11, "#616a73", 400, 312)
  text(180, 441, "tuskometr.com", 26, "#b04338", 600, 312)
  return new Promise((resolve, reject) => canvas.toBlob(
    blob => blob ? resolve(blob) : reject(new Error("Nie można utworzyć PNG")), "image/png"))
}
