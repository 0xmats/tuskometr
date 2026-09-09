import { useEffect, useState } from "react"
import type { Manifest } from "@/lib/api"
import { serverTimelineOrigin } from "@/lib/server-timeline"
import type { TimelineState } from "@/lib/youtube-timeline"

export function useYouTubeTimelineOrigin(videoId: string, manifest: Manifest | undefined, pending: boolean, nowMs: number) {
  const serverOrigin = serverTimelineOrigin(manifest, videoId, nowMs)
  const serverReady = serverOrigin !== null
  const [state, setState] = useState<TimelineState>({ origin: null, status: "loading" })
  const [generation, setGeneration] = useState(0)
  useEffect(() => {
    if (import.meta.env.DEV && import.meta.env.VITE_MOCK_DATA === "true") {
      setState({ origin: null, status: "disabled" })
      return
    }
    // Wait for the first manifest before deciding whether a local player is needed.
    // Normal visits never load YouTube; older publishers and outages retain fallback.
    if (pending || serverReady) return
    let disposed = false
    let stop: (() => void) | undefined
    setState({ origin: null, status: "loading" })
    void import("@/lib/youtube-timeline").then(({ startYouTubeTimeline }) => {
      if (!disposed) stop = startYouTubeTimeline(videoId, setState)
    }).catch(() => {
      if (!disposed) setState({ origin: null, status: "error" })
    })
    return () => { disposed = true; stop?.() }
  }, [videoId, generation, pending, serverReady])
  return {
    ...(serverReady ? { origin: serverOrigin, status: "ready" as const } : state),
    retry: () => {
      setState({ origin: null, status: "loading" })
      setGeneration(value => value + 1)
    },
  }
}
