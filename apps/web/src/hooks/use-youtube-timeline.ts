import { useEffect, useState } from "react"
import { startYouTubeTimeline, type TimelineState } from "@/lib/youtube-timeline"

export function useYouTubeTimelineOrigin(videoId: string) {
  const [state, setState] = useState<TimelineState>({ origin: null, status: "loading" })
  const [generation, setGeneration] = useState(0)
  useEffect(() => {
    if (import.meta.env.DEV && import.meta.env.VITE_MOCK_DATA === "true") {
      setState({ origin: null, status: "disabled" })
      return
    }
    return startYouTubeTimeline(videoId, setState)
  }, [videoId, generation])
  return { ...state, retry: () => {
    setState({ origin: null, status: "loading" })
    setGeneration((value) => value + 1)
  } }
}
