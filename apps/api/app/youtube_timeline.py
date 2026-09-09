"""Calibrate YouTube watch-link time once on the server, for all visitors."""
from __future__ import annotations

import argparse
import fcntl
import json
import logging
import math
import os
import re
import signal
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from .config import Settings, get_settings

logger = logging.getLogger("tuskometr.youtube_timeline")


def video_id(source_url: str) -> str:
    url = urlsplit(source_url)
    if url.hostname == "youtu.be":
        value = url.path.lstrip("/")
    elif url.hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        value = parse_qs(url.query).get("v", [""])[0]
    else:
        value = ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        raise ValueError("Expected a YouTube watch URL")
    return value


def valid_calibration(value: object, expected_video: str, now: float) -> bool:
    if not isinstance(value, dict) or value.get("videoId") != expected_video:
        return False
    numbers = [value.get(key) for key in ("origin", "checkedAt", "expiresAt")]
    if any(type(number) not in (int, float) or not math.isfinite(number) for number in numbers):
        return False
    origin, checked, expires = numbers
    return 0 < origin < checked - 1000 and checked <= now < expires <= checked + 300


def read_calibration(settings: Settings, now: float | None = None) -> dict | None:
    if settings.source_mode != "youtube":
        return None
    try:
        value = json.loads(settings.youtube_timeline_file.read_text())
        if valid_calibration(value, video_id(settings.source_url), time.time() if now is None else now):
            return {key: value[key] for key in ("videoId", "origin", "checkedAt", "expiresAt")}
    except (OSError, ValueError, TypeError):
        pass
    return None


def write_calibration(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".youtube-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as file:
            json.dump(value, file, allow_nan=False, separators=(",", ":"))
            file.flush()
            os.fsync(file.fileno())
        os.chmod(name, 0o644)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


# Same live-edge measurement as the browser fallback. Require advancing playback
# after seeking, rather than publishing a pre-seek or stalled player position.
PLAYER_SCRIPT = """videoId => new Promise((resolve, reject) => {
  let player, poll, finished = false;
  const finish = (value, error) => {
    if (finished) return;
    finished = true;
    clearInterval(poll); clearTimeout(deadline);
    try { player?.destroy() } catch {}
    if (error) reject(new Error(error)); else resolve(value);
  };
  const deadline = setTimeout(() => finish(null, 'Player timeout'), 30000);
  window.onYouTubeIframeAPIReady = () => {
    player = new YT.Player('player', {
      videoId, width: 640, height: 360,
      playerVars: {autoplay: 0, controls: 0, playsinline: 1, origin: location.origin},
      events: {
        onError: () => finish(null, 'Player error'),
        onAutoplayBlocked: () => finish(null, 'Playback blocked'),
        onReady: ({target}) => {
          target.mute(); target.playVideo();
          let soughtAt = null, previous = null;
          poll = setInterval(() => {
            const duration = target.getDuration();
            if (!Number.isFinite(duration) || duration <= 1000) return;
            if (soughtAt === null) {
              target.seekTo(1000000000, true); soughtAt = performance.now(); return;
            }
            if (performance.now() - soughtAt < 1500 || target.getPlayerState() !== 1) return;
            const position = target.getCurrentTime();
            if (!Number.isFinite(position) || position <= 1000) return;
            if (previous !== null && position > previous && position - previous < 2) {
              finish({origin: Date.now() / 1000 - position});
            }
            previous = position;
          }, 250);
        }
      }
    });
  };
  const script = document.createElement('script');
  script.src = 'https://www.youtube.com/iframe_api';
  script.onerror = () => finish(null, 'API unavailable');
  document.head.append(script);
})"""


def browser_proxy(raw: str) -> dict | None:
    if not raw:
        return None
    url = urlsplit(raw)
    host = f"[{url.hostname}]" if ":" in url.hostname else url.hostname
    result = {"server": f"{url.scheme}://{host}:{url.port}"}
    if url.username is not None:
        result.update(username=unquote(url.username), password=unquote(url.password or ""))
    return result


def measure(settings: Settings) -> dict:
    from playwright.sync_api import sync_playwright

    source = video_id(settings.source_url)
    page_url = settings.youtube_player_origin.rstrip("/") + "/__timeline_calibration"
    origins = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, args=["--autoplay-policy=no-user-gesture-required"],
            proxy=browser_proxy(settings.youtube_proxy_url.get_secret_value()),
        )
        try:
            # Independent cookie-free sessions detect session-specific offsets
            # and stream resets occurring during the measurement.
            for _ in range(2):
                context = browser.new_context(service_workers="block")
                try:
                    page = context.new_page()
                    page.route(page_url, lambda route: route.fulfill(
                        content_type="text/html",
                        body='<!doctype html><html><body><div id="player"></div></body></html>',
                    ))
                    page.goto(page_url, wait_until="domcontentloaded", timeout=10000)
                    sample = page.evaluate(PLAYER_SCRIPT, source)
                    origin = sample["origin"]
                    if type(origin) not in (float, int) or not math.isfinite(origin):
                        raise ValueError("Invalid player position")
                    origins.append(origin)
                finally:
                    context.close()
        finally:
            browser.close()
    if abs(origins[0] - origins[1]) > 10:
        # A previously cached offset cannot be trusted across a possible reset.
        settings.youtube_timeline_file.unlink(missing_ok=True)
        raise ValueError("Independent player sessions disagree")
    checked = time.time()
    value = {
        "videoId": source, "origin": sum(origins) / len(origins),
        "checkedAt": checked, "expiresAt": checked + settings.youtube_timeline_max_age_seconds,
    }
    if not valid_calibration(value, source, checked):
        raise ValueError("Invalid calibration")
    return value


def calibrate_once(settings: Settings) -> dict:
    value = measure(settings)
    write_calibration(settings.youtube_timeline_file, value)
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Measure, write and exit")
    parser.add_argument("--check", action="store_true", help="Check the cached measurement")
    args = parser.parse_args()
    settings = get_settings()
    if args.check:
        raise SystemExit(0 if read_calibration(settings) else 1)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    settings.youtube_timeline_file.parent.mkdir(parents=True, exist_ok=True)
    with settings.youtube_timeline_file.with_suffix(".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while not stop.is_set():
            try:
                calibrate_once(settings)
                logger.info("YouTube timeline calibrated and verified in two sessions")
            except Exception as error:
                # Browser exceptions can contain signed media URLs or proxy credentials.
                logger.warning("YouTube calibration failed (%s)", type(error).__name__)
                if args.once:
                    raise SystemExit(1) from None
            if args.once:
                break
            stop.wait(settings.youtube_timeline_interval_seconds)


if __name__ == "__main__":
    main()
