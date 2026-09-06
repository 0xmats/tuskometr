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
      events: { onReady: (event: YouTubePlayerEvent) => void; onError: () => void; onAutoplayBlocked: () => void }
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
let apiPromise: Promise<YouTubeApi> | undefined

function loadYouTubeApi(): Promise<YouTubeApi> {
  if (window.YT?.Player) return Promise.resolve(window.YT)
  if (apiPromise) return apiPromise
  apiPromise = new Promise<YouTubeApi>((resolve, reject) => {
    const previous = window.onYouTubeIframeAPIReady
    const script = document.createElement("script")
    let settled = false
    const finish = (error?: Error) => {
      if (settled) return
      settled = true
      window.clearTimeout(timer)
      script.onerror = null
      if (window.onYouTubeIframeAPIReady === ready) window.onYouTubeIframeAPIReady = previous
      if (error) { script.remove(); reject(error) }
      else resolve(window.YT!)
    }
    const ready = () => {
      if (window.YT?.Player) finish()
      else finish(new Error("YouTube API unavailable"))
      previous?.()
    }
    const timer = window.setTimeout(() => finish(new Error("YouTube API timeout")), 15_000)
    window.onYouTubeIframeAPIReady = ready
    script.src = YOUTUBE_API_URL
    script.async = true
    script.onerror = () => finish(new Error("YouTube API failed"))
    document.head.append(script)
  }).catch((error) => { apiPromise = undefined; throw error })
  return apiPromise
}

export type TimelineState = {
  origin: number | null
  status: "loading" | "retrying" | "ready" | "error" | "disabled"
}

// One calibration session per dashboard, shared by all mention links.
export function startYouTubeTimeline(videoId: string, update: (state: TimelineState) => void) {
  let disposed = false
  let attempts = 0
  let retryTimer: number | undefined
  let cleanAttempt = () => {}

  const attempt = () => {
    if (disposed) return
    attempts += 1
    let finished = false
    let player: YouTubePlayer | undefined
    let mount: HTMLDivElement | undefined
    let poll: number | undefined
    let seekTimer: number | undefined
    const deadline = window.setTimeout(() => fail(), 25_000)
    const cleanup = () => {
      window.clearTimeout(deadline)
      window.clearInterval(poll)
      window.clearTimeout(seekTimer)
      try { player?.destroy() } catch { /* Player may already be detached. */ }
      player = undefined
      mount?.remove()
      mount = undefined
    }
    cleanAttempt = () => { finished = true; cleanup() }
    const fail = () => {
      if (finished || disposed) return
      finished = true
      cleanup()
      if (attempts < 3) {
        update({ origin: null, status: "retrying" })
        retryTimer = window.setTimeout(attempt, attempts * 2_000)
      } else update({ origin: null, status: "error" })
    }
    update({ origin: null, status: attempts === 1 ? "loading" : "retrying" })
    void loadYouTubeApi().then((YT) => {
      if (finished || disposed) return
      mount = document.createElement("div")
      mount.setAttribute("aria-hidden", "true")
      mount.style.cssText = "position:fixed;width:1px;height:1px;left:-10000px;top:-10000px;opacity:0;pointer-events:none"
      document.body.append(mount)
      player = new YT.Player(mount, {
        videoId, width: 1, height: 1,
        playerVars: { autoplay: 0, controls: 0, disablekb: 1, playsinline: 1, origin: window.location.origin },
        events: {
          onError: fail,
          onAutoplayBlocked: fail,
          onReady: ({ target }) => {
            if (finished || disposed) return
            try {
              target.mute()
              target.playVideo()
              poll = window.setInterval(() => {
                if (finished || disposed) return
                try {
                  const duration = target.getDuration()
                  if (!Number.isFinite(duration) || duration <= 1_000) return
                  window.clearInterval(poll)
                  target.seekTo(1_000_000_000, true)
                  seekTimer = window.setTimeout(() => {
                    if (finished || disposed) return
                    try {
                      const position = target.getCurrentTime()
                      if (!Number.isFinite(position) || position <= 1_000) { fail(); return }
                      const origin = Date.now() / 1_000 - position
                      finished = true
                      cleanup()
                      update({ origin, status: "ready" })
                    } catch { fail() }
                  }, 1_500)
                } catch { fail() }
              }, 250)
            } catch { fail() }
          },
        },
      })
    }).catch(fail)
  }
  attempt()
  return () => {
    disposed = true
    window.clearTimeout(retryTimer)
    cleanAttempt()
  }
}
