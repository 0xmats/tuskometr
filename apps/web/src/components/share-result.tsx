import { useEffect, useRef, useState } from "react"
import { Copy, Download, Share2, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { Dashboard } from "@/lib/api"
import { renderShareCard, shareUrl, snapshotAlt, snapshotDate, snapshotFromDashboard, type ShareSnapshot } from "@/lib/share"

function ShareCard({ snapshot }: { snapshot: ShareSnapshot }) {
  const [card, setCard] = useState<{ url: string; blob: Blob } | null>(null)
  const [error, setError] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [message, setMessage] = useState("")
  const active = useRef(false)
  const pageUrl = shareUrl()
  useEffect(() => {
    let cancelled = false
    let url: string | undefined
    active.current = true
    setCard(null)
    setError(false)
    renderShareCard(snapshot).then(blob => {
      if (cancelled) return
      url = URL.createObjectURL(blob)
      setCard({ url, blob })
    }).catch(() => { if (!cancelled) setError(true) })
    return () => {
      cancelled = true
      active.current = false
      if (url) URL.revokeObjectURL(url)
    }
  }, [snapshot, attempt])

  async function copy() {
    try {
      await navigator.clipboard.writeText(pageUrl)
      if (active.current) setMessage("Link skopiowany.")
    } catch {
      if (active.current) setMessage("Zaznacz i skopiuj link z pola poniżej.")
    }
  }

  const filename = `tuskometr-${snapshot.generatedAt.replace(/[^0-9]/g, "").slice(0, 14)}.png`
  async function share() {
    try {
      const file = card ? new File([card.blob], filename, { type: "image/png" }) : null
      // The image is ready before the click, preserving native user activation.
      const files = file && navigator.canShare?.({ files: [file] }) ? [file] : undefined
      await navigator.share({ title: "Tuskometr", url: pageUrl, ...(files ? { files } : {}) })
    } catch (error) {
      if (active.current && !(error instanceof DOMException && error.name === "AbortError")) {
        setMessage("Udostępnianie jest niedostępne. Skopiuj link lub pobierz PNG.")
      }
    }
  }

  return <>
    <div className="my-5 overflow-hidden rounded-xl border border-slate-200 bg-slate-50">
      {error ? <div className="p-5"><p role="alert" className="text-sm">Nie udało się utworzyć obrazka.</p>
        <Button variant="outline" className="mt-3" onClick={() => setAttempt(value => value + 1)}>Spróbuj ponownie</Button></div>
        : card ? <img src={card.url} width="1200" height="630" className="h-auto w-full" alt={snapshotAlt(snapshot)} />
          : <p role="status" className="p-5 text-sm">Przygotowywanie podglądu…</p>}
    </div>
    <div className="flex flex-wrap gap-2">
      <Button onClick={copy}><Copy className="size-4" />Kopiuj link</Button>
      {card ? <Button variant="outline" asChild><a href={card.url} download={filename}><Download className="size-4" />Pobierz PNG</a></Button>
        : <Button variant="outline" disabled><Download className="size-4" />Pobierz PNG</Button>}
      {typeof navigator.share === "function" && <Button variant="outline" onClick={share}><Share2 className="size-4" />Udostępnij…</Button>}
    </div>
    <label htmlFor="share-link" className="mt-5 block text-xs text-muted-foreground">Link do aktualnej strony</label>
    <input id="share-link" readOnly value={pageUrl} onFocus={event => event.target.select()}
      className="mt-2 w-full rounded-md border border-slate-200 p-2 text-sm focus:outline-primary" />
    <p role="status" className="mt-2 min-h-5 text-sm">{message}</p>
    <p className="text-xs text-muted-foreground">PNG zachowuje pokazany wynik. Link prowadzi do aktualnych statystyk.</p>
  </>
}

export function ShareResult({ dashboard }: { dashboard?: Dashboard }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [snapshot, setSnapshot] = useState<ShareSnapshot | null>(null)
  useEffect(() => {
    if (!snapshot) return
    const element = dialog.current!
    element.showModal()
    const overflow = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      element.close()
      document.body.style.overflow = overflow
    }
  }, [snapshot])
  return <>
    <Button variant="outline" disabled={!dashboard} onClick={() => {
      setSnapshot(snapshotFromDashboard(dashboard!, import.meta.env.VITE_MOCK_DATA === "true"))
    }}><Share2 className="size-4" />Udostępnij wynik</Button>
    {snapshot && <dialog ref={dialog} aria-labelledby="share-title" aria-describedby="share-description"
      onClose={() => setSnapshot(null)}
      onClick={event => { if (event.target === event.currentTarget) dialog.current?.close() }}
      className="m-auto max-h-[90dvh] w-[calc(100%-2rem)] max-w-3xl overflow-y-auto rounded-2xl border border-slate-200 bg-white p-0 text-foreground shadow-xl backdrop:bg-slate-950/50">
      <div className="p-5 sm:p-7">
        <div className="flex items-start justify-between gap-4">
          <div><h2 id="share-title" className="text-xl font-semibold">Udostępnij wynik</h2>
            <p id="share-description" className="mt-2 text-sm text-muted-foreground">Obrazek przedstawia stan z {snapshotDate(snapshot)} (czas polski).</p>
          </div>
          <Button autoFocus variant="ghost" size="icon" aria-label="Zamknij" className="shrink-0"
            onClick={() => dialog.current?.close()}><X className="size-5" /></Button>
        </div>
        <ShareCard snapshot={snapshot} />
        <a href={shareUrl()} target="_blank" rel="noreferrer" className="mt-3 inline-block text-sm text-primary underline underline-offset-4">Otwórz aktualną stronę</a>
      </div>
    </dialog>}
  </>
}
