import { useEffect, useRef, useState } from "react"
import { Check, Copy, Download, Loader2, Share2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { Dashboard } from "@/lib/api"
import { renderShareCard, shareUrl, snapshotFromDashboard } from "@/lib/share"

export function ShareResult({ dashboard }: { dashboard?: Dashboard }) {
  const container = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const operation = useRef(0)
  const [alignLeft, setAlignLeft] = useState(false)
  const [open, setOpen] = useState(false)
  const [copyState, setCopyState] = useState<"copying" | "copied" | "failed">("copying")
  const [busy, setBusy] = useState(false)
  const [imageCopied, setImageCopied] = useState(false)
  const [fallback, setFallback] = useState<{ blob: Blob; filename: string } | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    return () => { operation.current++ }
  }, [])

  useEffect(() => {
    if (!open) return
    const position = () => setAlignLeft((container.current?.getBoundingClientRect().right ?? 0) < 276)
    position()
    window.addEventListener("resize", position)
    const dismiss = () => {
      operation.current++
      setOpen(false)
      setBusy(false)
    }
    const outside = (event: PointerEvent) => {
      if (!container.current?.contains(event.target as Node)) dismiss()
    }
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        dismiss()
        trigger.current?.focus()
      }
    }
    document.addEventListener("pointerdown", outside)
    document.addEventListener("keydown", escape)
    return () => {
      window.removeEventListener("resize", position)
      document.removeEventListener("pointerdown", outside)
      document.removeEventListener("keydown", escape)
    }
  }, [open])

  async function copy() {
    const current = ++operation.current
    setOpen(true)
    setCopyState("copying")
    setImageCopied(false)
    setFallback(null)
    setError(false)
    setBusy(false)
    try {
      await navigator.clipboard.writeText(shareUrl())
      if (operation.current === current) setCopyState("copied")
    } catch {
      if (operation.current === current) setCopyState("failed")
    }
  }

  async function copyImage() {
    if (!dashboard || busy) return
    const current = operation.current
    const snapshot = snapshotFromDashboard(dashboard, import.meta.env.VITE_MOCK_DATA === "true")
    const filename = `tuskometr-${snapshot.generatedAt.replace(/[^0-9]/g, "").slice(0, 14)}.png`
    setBusy(true)
    setError(false)
    setImageCopied(false)
    setFallback(null)
    // Pass the pending PNG to ClipboardItem while user activation is still live
    // (not after awaiting canvas/font rendering, which can fail in Safari).
    const png = renderShareCard(snapshot)
    // Rendering can reject before clipboard permissions resolve.
    void png.catch(() => {})
    try {
      if (!navigator.clipboard?.write || typeof ClipboardItem === "undefined") throw new Error("Clipboard unavailable")
      await navigator.clipboard.write([new ClipboardItem({ "image/png": png })])
      if (operation.current === current) setImageCopied(true)
    } catch {
      try {
        const blob = await png
        if (operation.current === current) setFallback({ blob, filename })
      } catch {
        if (operation.current === current) setError(true)
      }
    } finally {
      if (operation.current === current) setBusy(false)
    }
  }

  function download() {
    if (!fallback) return
    const url = URL.createObjectURL(fallback.blob)
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = fallback.filename
    document.body.append(anchor)
    anchor.click()
    anchor.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  }

  return <div ref={container} className="relative">
    <Button ref={trigger} variant="outline" disabled={busy} onClick={copy} aria-expanded={open} aria-controls="share-options">
      <Share2 className="size-4" />Udostępnij
    </Button>
    {open && <div id="share-options" role="region" aria-label="Udostępnianie"
      className={`absolute ${alignLeft ? "left-0" : "right-0"} top-full z-30 mt-2 w-64 max-w-[calc(100vw-2.5rem)] rounded-xl border border-slate-200 bg-white p-3 shadow-lg`}>
      <p role="status" className="flex items-center gap-2 px-1 py-2 text-sm">
        {(imageCopied || copyState === "copied") && <Check className="size-4 text-primary" />}
        {imageCopied ? "Obrazek skopiowany" : copyState === "copied" ? "Link skopiowany" : copyState === "copying" ? "Kopiowanie linku…" : "Skopiuj link ręcznie:"}
      </p>
      {copyState === "failed" && !imageCopied && <input aria-label="Link do strony" readOnly value={shareUrl()}
        onFocus={event => event.target.select()}
        className="mb-2 w-full rounded-md border border-slate-200 p-2 text-sm focus:outline-primary" />}
      {fallback ? <>
        <p className="px-1 py-2 text-xs text-muted-foreground">Nie można skopiować obrazka. Możesz go pobrać.</p>
        <Button variant="ghost" className="w-full justify-start" onClick={download}>
          <Download className="size-4" />Pobierz PNG
        </Button>
      </> : <Button variant="ghost" className="w-full justify-start" disabled={!dashboard || busy} onClick={copyImage}>
        {busy ? <Loader2 className="size-4 animate-spin" /> : <Copy className="size-4" />}
        {busy ? "Kopiowanie obrazka…" : "Kopiuj obrazek"}
      </Button>}
      {error && <p role="alert" className="px-1 pt-2 text-xs text-primary">Nie udało się utworzyć PNG. Spróbuj ponownie.</p>}
    </div>}
  </div>
}
