import { useEffect, useId, useRef, useState } from "react"
import { Check, Copy, Download, Loader2, Share2, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { Dashboard } from "@/lib/api"
import { renderShareCard, shareUrl, snapshotAlt, snapshotFromDashboard, type ShareSnapshot } from "@/lib/share"

export function ShareResult({ dashboard }: { dashboard?: Dashboard }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const operation = useRef(0)
  const titleId = useId()
  const [snapshot, setSnapshot] = useState<ShareSnapshot | null>(null)
  const [image, setImage] = useState<{ file: File; url: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState("")
  const [error, setError] = useState("")
  const [manualLink, setManualLink] = useState(false)

  useEffect(() => {
    if (!snapshot) return
    const current = ++operation.current
    let imageUrl: string | undefined
    const modal = dialog.current
    modal?.showModal()
    setImage(null)
    setBusy(false)
    setNotice("")
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
    files: [image.file], title: "Tuskometr",
  } : null
  let nativeShare = false
  try {
    nativeShare = !!shareData && typeof navigator.share === "function" &&
      typeof navigator.canShare === "function" && navigator.canShare(shareData)
  } catch { /* Use clipboard and download when file sharing is unavailable. */ }

  const canCopyImage = typeof navigator.clipboard?.write === "function" && typeof ClipboardItem !== "undefined"

  async function shareImage(useNative = false) {
    if (!image || !shareData || busy) return
    const current = operation.current
    setBusy(true)
    setNotice("")
    setError("")
    try {
      if (useNative) {
        await navigator.share(shareData)
      } else {
        await navigator.clipboard.write([new ClipboardItem({ "image/png": image.file })])
        if (operation.current === current) setNotice("Obrazek skopiowany. Wklej go do wiadomości lub posta.")
      }
    } catch (error) {
      if (operation.current === current && !(error instanceof Error && error.name === "AbortError")) {
        setError("Nie udało się przekazać obrazka. Pobierz go i dołącz do wiadomości.")
      }
    } finally {
      if (operation.current === current) setBusy(false)
    }
  }

  async function copyLink() {
    const current = operation.current
    try {
      await navigator.clipboard.writeText(shareUrl())
      if (operation.current === current) {
        setManualLink(false)
        setNotice("Link skopiowany.")
      }
    } catch {
      if (operation.current === current) setManualLink(true)
    }
  }

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
        {image && snapshot ? <img src={image.url} alt={snapshotAlt(snapshot)} width={640} height={240} className="block h-auto w-full" />
          : <div className="flex aspect-[8/3] items-center justify-center gap-2 text-sm text-muted-foreground">
            {!error && <><Loader2 className="size-4 animate-spin" aria-hidden="true" />Przygotowywanie obrazka…</>}
          </div>}
      </div>
      <div className="p-4 sm:p-5">
        <div className="flex flex-wrap items-center gap-2">
          <Button disabled={!image || busy} onClick={() => void shareImage(!canCopyImage && nativeShare)} className="w-full sm:w-auto">
            {busy ? <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              : !canCopyImage && nativeShare ? <Share2 className="size-4" aria-hidden="true" /> : <Copy className="size-4" aria-hidden="true" />}
            {!canCopyImage && nativeShare ? "Udostępnij obrazek" : "Kopiuj obrazek"}
          </Button>
          {canCopyImage && nativeShare && <Button variant="ghost" disabled={!image || busy} onClick={() => void shareImage(true)}>
            <Share2 className="size-4" aria-hidden="true" />Udostępnij
          </Button>}
          {image && <Button asChild variant="ghost"><a href={image.url} download={image.file.name}>
            <Download className="size-4" aria-hidden="true" />Pobierz
          </a></Button>}
          <Button variant="ghost" onClick={copyLink} disabled={busy}>
            <Copy className="size-4" aria-hidden="true" />Kopiuj link
          </Button>
        </div>
        <p aria-live="polite" className={notice ? "mt-3 flex items-start gap-2 text-sm text-muted-foreground" : "sr-only"}>
          {notice && <Check className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden="true" />}{notice}
        </p>
        {error && <p role="alert" className="mt-3 text-sm text-primary">{error}</p>}
        {manualLink && <label className="mt-3 block text-sm">Skopiuj link:
          <input autoFocus readOnly value={shareUrl()} onFocus={event => event.target.select()}
            className="mt-1 w-full rounded-md border border-slate-200 p-2" />
        </label>}
      </div>
    </dialog>
  </>
}
