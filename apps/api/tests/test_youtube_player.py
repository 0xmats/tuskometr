"""Exercise the server player logic with a deterministic YouTube API clock."""
import json
import subprocess

from app.youtube_timeline import PLAYER_SCRIPT


def test_server_player_handles_seek_playback_errors_and_deadlines():
    script = r"""
const assert = require('node:assert/strict');
const measure = eval(process.argv[1]);
async function run(mode) {
  let now = 0, serial = 0, destroyed = 0, sought = false, readyAt = null;
  const timers = new Map();
  const timer = (fn, delay, interval=false) => {
    const id = ++serial; timers.set(id, {fn, at:now+delay, delay, interval}); return id;
  };
  global.setTimeout = (fn, delay) => timer(fn, delay);
  global.setInterval = (fn, delay) => timer(fn, delay, true);
  global.clearTimeout = global.clearInterval = id => timers.delete(id);
  global.performance = {now: () => now};
  Date.now = () => 1800000000000 + now;
  global.location = {origin:'https://example.com'};
  global.window = global;
  global.document = {
    createElement: () => ({}),
    head: {append: script => {
      if (mode === 'script-error') timer(() => script.onerror(), 0);
      else if (mode !== 'script-timeout') timer(() => onYouTubeIframeAPIReady(), 0);
    }}
  };
  global.YT = {Player: class {
    constructor(id, options) {
      timer(() => {
        if (mode === 'player-error') options.events.onError();
        else if (mode === 'blocked') options.events.onAutoplayBlocked();
        else options.events.onReady({target:this});
      }, 0);
    }
    mute() {}
    playVideo() {}
    getDuration() {return mode === 'no-metadata' ? 0 : 100000;}
    seekTo() {sought = true;}
    getPlayerState() {return mode === 'buffering' ? 3 : 1;}
    getCurrentTime() {
      if (mode === 'invalid') return NaN;
      if (mode === 'stalled') return 99990;
      return 99990 + now / 1000;
    }
    destroy() {destroyed++;}
  }};
  let value, error;
  const result = measure('dzntyCTgJMQ').then(v => {value=v; readyAt=now;}, e => {error=e;});
  while (timers.size) {
    const [id,t] = [...timers].sort((a,b) => a[1].at-b[1].at)[0];
    now=t.at;
    if(t.interval)t.at+=t.delay;else timers.delete(id);
    t.fn();
    await Promise.resolve();
  }
  await result;
  if(mode==='success') {
    assert.ok(sought);
    assert.ok(readyAt >= 2000, 'wait for seek completion and advancing playback');
    assert.equal(value.origin, 1800000000-99990);
    assert.equal(error, undefined);
  } else {assert.ok(error,mode);assert.equal(value,undefined);}
  assert.equal(destroyed,mode.startsWith('script-')?0:1,mode);
}
(async()=>{for (const mode of ['success','script-error','script-timeout','player-error',
  'blocked','no-metadata','buffering','invalid','stalled']) await run(mode);})()
.catch(error => {console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(["node", "-e", script, PLAYER_SCRIPT], capture_output=True,
                            text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_disagreeing_sessions_invalidate_cached_result(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from app.config import Settings
    from app.youtube_timeline import measure

    settings = Settings(_env_file=None, youtube_timeline_file=tmp_path / "youtube.json")
    settings.youtube_timeline_file.write_text(json.dumps({"origin": 123}))
    closed = []
    results = iter([{"origin": 1_700_000_000}, {"origin": 1_700_000_020}])
    page = SimpleNamespace(route=lambda *args: None, goto=lambda *args, **kw: None,
                           evaluate=lambda *args: next(results))
    context = SimpleNamespace(new_page=lambda: page, close=lambda: closed.append("context"))
    browser = SimpleNamespace(new_context=lambda **kw: context,
                              close=lambda: closed.append("browser"))

    class Playwright:
        def __enter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kw: browser))

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("playwright.sync_api.sync_playwright", Playwright)
    import pytest

    with pytest.raises(ValueError, match="disagree"):
        measure(settings)
    assert not settings.youtube_timeline_file.exists()
    assert closed == ["context", "context", "browser"]
