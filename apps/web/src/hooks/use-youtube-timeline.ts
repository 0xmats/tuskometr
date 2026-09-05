import { useEffect, useState } from "react"

type YouTubePlayer = {
  destroy: () => void
  getCurrentTime: () => number
  getDuration: () => number
  mute: () => void
  pauseVideo: () => void
  playVideo: () => void
  seekTo: (seconds: number, allowSeekAhead: boolean) => void
}

type YouTubePlayerEvent = {
  target: YouTubePlayer
}

type YouTubeApi = {
  Player: new (
    element: HTMLElement,
    options: {
      videoId: string
      width: number
      height: number
      playerVars: Record<string, number | string>
      events: { onReady: (event: YouTubePlayerEvent) => void }
    },
  ) => YouTubePlayer
}

declare global {
  interface Window {
    YT?: YouTubeApi
    onYouTubeIframeAPIReady?: () => void
  }
}

const YOUTUBE_API_URL = "https://www.youtube.com/iframe_api"
const LIVE_EDGE_SEEK_SECONDS = 1_000_000_000

let apiPromise: Promise<YouTubeApi> | undefined

function loadYouTubeApi(): Promise<YouTubeApi> {
  if (window.YT?.Player) return Promise.resolve(window.YT)
  if (apiPromise) return apiPromise

  apiPromise = new Promise((resolve) => {
    const previousReady = window.onYouTubeIframeAPIReady
    window.onYouTubeIframeAPIReady = () => {
      previousReady?.()
      if (window.YT) resolve(window.YT)
    }

    if (!document.querySelector(`script[src="${YOUTUBE_API_URL}"]`)) {
      const script = document.createElement("script")
      script.src = YOUTUBE_API_URL
      script.async = true
      document.head.append(script)
    }
  })
  return apiPromise
}

/**
 * YouTube resets the live player's media timeline when the permanent stream is
 * restarted. Seeking a muted player past its end makes YouTube clamp it to the
 * active live edge, whose getCurrentTime() value is exactly what the watch URL's
 * `t` parameter accepts.
 */
export function useYouTubeTimelineOrigin(videoId: string): number | null {
  const [origin, setOrigin] = useState<number | null>(null)

  useEffect(() => {
    let disposed = false
    let player: YouTubePlayer | undefined
    let calibrationTimer: number | undefined
    let finishTimer: number | undefined
    const mount = document.createElement("div")
    mount.setAttribute("aria-hidden", "true")
    mount.style.cssText =
      "position:fixed;width:1px;height:1px;left:-10000px;top:-10000px;opacity:0;pointer-events:none"
    document.body.append(mount)

    void loadYouTubeApi().then((YT) => {
      if (disposed) return
      player = new YT.Player(mount, {
        videoId,
        width: 1,
        height: 1,
        playerVars: {
          autoplay: 0,
          controls: 0,
          disablekb: 1,
          playsinline: 1,
          origin: window.location.origin,
        },
        events: {
          onReady: ({ target }) => {
            // A cued live video reports duration=0. Starting it muted lets the
            // player load timeline metadata; it is paused immediately after
            // calibration and no media is retained by the application.
            target.mute()
            target.playVideo()
            calibrationTimer = window.setInterval(() => {
              const duration = target.getDuration()
              if (!Number.isFinite(duration) || duration <= 1_000) return
              window.clearInterval(calibrationTimer)
              target.seekTo(LIVE_EDGE_SEEK_SECONDS, true)
              finishTimer = window.setTimeout(() => {
                const livePosition = target.getCurrentTime()
                target.pauseVideo()
                if (!disposed && Number.isFinite(livePosition) && livePosition > 1_000) {
                  setOrigin(Date.now() / 1_000 - livePosition)
                }
              }, 1_500)
            }, 250)
          },
        },
      })
    })

    return () => {
      disposed = true
      window.clearInterval(calibrationTimer)
      window.clearTimeout(finishTimer)
      player?.destroy()
      mount.remove()
    }
  }, [videoId])

  return origin
}
