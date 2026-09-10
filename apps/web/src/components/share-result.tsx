import { useEffect, useId, useRef, useState } from "react"
import { Check, Copy, Loader2, Share2, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { Dashboard } from "@/lib/api"
import { renderShareCard, shareUrl, snapshotAlt, snapshotFromDashboard, type ShareSnapshot } from "@/lib/share"

export function ShareResult({ dashboard }: { dashboard?: Dashboard }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const operation = useRef(0)
  const titleId = useId()
  const [snapshot, setSnapshot] = useState<ShareSnapshot | null>(null)
  const [image, setImage] = useState<{ file: File; url: string } | null>(null)
  type Action = "image" | "share" | "link"
  const pending = useRef(false)
  const [busy, setBusy] = useState<Action | null>(null)
  const [completed, setCompleted] = useState<Action | null>(null)

  useEffect(() => {
    if (!completed) return
    const timer = window.setTimeout(() => setCompleted(null), 1800)
    return () => window.clearTimeout(timer)
  }, [completed])
  const [error, setError] = useState("")
  const [manualLink, setManualLink] = useState(false)

  useEffect(() => {
    if (!snapshot) return
    const current = ++operation.current
    let imageUrl: string | undefined
    const modal = dialog.current
    modal?.showModal()
    setImage(null)
    pending.current = false
    setBusy(null)
    setCompleted(null)
    setError("")
    setManualLink(false)
    void renderShareCard(snapshot).then(blob => {
      if (operation.current !== current) return
      imageUrl = URL.createObjectURL(blob)
      const filename = `tuskometr-${snapshot.generatedAt.replace(/[^0-9]/g, "").slice(0, 14)}.png`
      setImage({ file: new File([blob], filename, { type: "image/png" }), url: imageUrl })
    }).catch(() => {
      if (operation.current === current) setError("Nie udało się przygotować obrazka. Zamknij okno i spróbuj ponownie.")
    })
    return () => {
      operation.current++
      modal?.close()
      if (imageUrl) URL.revokeObjectURL(imageUrl)
    }
  }, [snapshot])

  const shareData = image && snapshot ? {
    files: [image.file],
  } : null
  let nativeShare = false
  try {
    nativeShare = !!shareData && typeof navigator.share === "function" &&
      typeof navigator.canShare === "function" && navigator.canShare(shareData)
  } catch { /* Use the clipboard when file sharing is unavailable. */ }

  const canCopyImage = typeof navigator.clipboard?.write === "function" && typeof ClipboardItem !== "undefined"

  async function runAction(action: Action) {
    if (pending.current || completed === action) return
    if (action !== "link" && (!image || !shareData)) return
    const current = operation.current
    pending.current = true
    setBusy(action)
    setCompleted(null)
    setError("")
    setManualLink(false)
    try {
      if (action === "share") {
        // Pass only the file, with no additional share items or metadata.
        await navigator.share(shareData!)
      } else if (action === "image") {
        await navigator.clipboard.write([new ClipboardItem({ "image/png": image!.file })])
      } else {
        await navigator.clipboard.writeText(shareUrl())
      }
      if (operation.current === current) setCompleted(action)
    } catch (error) {
      if (operation.current === current && !(error instanceof Error && error.name === "AbortError")) {
        if (action === "link") setManualLink(true)
        else setError("Nie udało się przekazać obrazka. Spróbuj ponownie lub skopiuj link.")
      }
    } finally {
      if (operation.current === current) {
        pending.current = false
        setBusy(null)
      }
    }
  }

  function actionContent(action: Action, label: string, icon: React.ReactNode) {
    const done = completed === action
    return <>
      <span className={`flex items-center gap-2 transition-all duration-200 motion-reduce:transition-none ${done ? "scale-95 opacity-0" : "scale-100 opacity-100"}`}>
        {busy === action ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : icon}{label}
      </span>
      <span aria-hidden="true" className={`absolute inset-0 flex items-center justify-center gap-2 transition-all duration-200 motion-reduce:transition-none ${done ? "scale-100 opacity-100" : "scale-75 opacity-0"}`}>
        <Check className="size-5" strokeWidth={3} />OK
      </span>
    </>
  }
  const primaryAction = !canCopyImage && nativeShare ? "share" : "image"
  const primaryLabel = primaryAction === "share" ? "Udostępnij obrazek" : "Kopiuj obrazek"

  return <>
    <Button variant="outline" disabled={!dashboard || dashboard.stats.summary.lastHour == null}
      onClick={() => dashboard && setSnapshot(snapshotFromDashboard(dashboard, import.meta.env.VITE_MOCK_DATA === "true"))}>
      <Share2 className="size-4" aria-hidden="true" />Udostępnij wynik
    </Button>
    <dialog ref={dialog} aria-labelledby={titleId}
      onCancel={() => setSnapshot(null)}
      onClick={event => {
        if (event.target !== event.currentTarget) return
        const box = event.currentTarget.getBoundingClientRect()
        if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) setSnapshot(null)
      }}
      className="fixed inset-0 m-auto max-h-[calc(100dvh-2rem)] w-[calc(100vw-2rem)] max-w-lg overflow-y-auto rounded-2xl border border-slate-200 bg-white p-0 text-foreground shadow-xl backdrop:bg-black/40">
      <div className="flex items-center justify-between gap-4 px-5 py-3">
        <h2 id={titleId} className="text-base font-semibold">Udostępnij wynik</h2>
        <Button variant="ghost" size="icon" aria-label="Zamknij" onClick={() => setSnapshot(null)}>
          <X className="size-4" aria-hidden="true" />
        </Button>
      </div>
      <div className="border-y border-slate-200">
        {image && snapshot ? <img src={image.url} alt={snapshotAlt(snapshot)} width={360} height={480} className="mx-auto block h-auto max-h-[55dvh] w-auto max-w-full" />
          : <div className="mx-auto flex aspect-[3/4] max-h-[55dvh] items-center justify-center gap-2 text-sm text-muted-foreground">
            {!error && <><Loader2 className="size-4 animate-spin" aria-hidden="true" />Przygotowywanie obrazka…</>}
          </div>}
      </div>
      <div className="p-4 sm:p-5">
        <div className={`grid gap-2 ${canCopyImage && nativeShare ? "grid-cols-2" : "grid-cols-1"}`}>
          <Button aria-label={primaryLabel} disabled={!image || busy !== null} onClick={() => void runAction(primaryAction)} className="relative col-span-full w-full">
            {actionContent(primaryAction, primaryLabel, primaryAction === "share" ? <Share2 className="size-4" aria-hidden="true" /> : <Copy className="size-4" aria-hidden="true" />)}
          </Button>
          {canCopyImage && nativeShare && <Button aria-label="Udostępnij" variant="ghost" className="relative w-full" disabled={!image || busy !== null} onClick={() => void runAction("share")}>
            {actionContent("share", "Udostępnij", <Share2 className="size-4" aria-hidden="true" />)}
          </Button>}
          <Button aria-label="Kopiuj link" variant="ghost" className="relative w-full" onClick={() => void runAction("link")} disabled={busy !== null}>
            {actionContent("link", "Kopiuj link", <Copy className="size-4" aria-hidden="true" />)}
          </Button>
        </div>
        <span role="status" className="sr-only">{completed === "image" ? "Obrazek skopiowany" : completed === "link" ? "Link skopiowany" : completed === "share" ? "Przekazano do udostępniania" : ""}</span>
        {error && <p role="alert" className="mt-3 text-sm text-primary">{error}</p>}
        {manualLink && <label className="mt-3 block text-sm">Skopiuj link:
          <input autoFocus readOnly value={shareUrl()} onFocus={event => event.target.select()}
            className="mt-1 w-full rounded-md border border-slate-200 p-2" />
        </label>}
      </div>
    </dialog>
  </>
}
