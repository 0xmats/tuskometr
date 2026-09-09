import type { Manifest } from "./api"

export function serverTimelineOrigin(manifest: Manifest | undefined, videoId: string, nowMs: number): number | null {
  const sample = manifest?.youtubeTimeline
  if (!manifest || !sample || sample.videoId !== videoId) return null
  const { origin, checkedAt, expiresAt } = sample
  if (![origin, checkedAt, expiresAt].every(value => typeof value === "number" && Number.isFinite(value))) return null
  // CDN Date/Age plus monotonic elapsed time also work with an incorrect device clock.
  const now = (manifest.serverTimeAtReceiptMs + Math.max(0, nowMs - manifest.receivedAtMs)) / 1000
  if (!Number.isFinite(now) || origin <= 0 || origin >= checkedAt - 1000 ||
      checkedAt > now + 1 || now >= expiresAt || expiresAt > checkedAt + 300) return null
  return origin
}
