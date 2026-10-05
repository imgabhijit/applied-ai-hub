// Full-screen vertical viewer for the Shorts tab: swipe up for the next video, swipe down for the previous one.
//   touch / mouse drag : swipe up or down on the video     wheel : scroll down / up
//   keyboard           : ArrowDown / J / PageDown = next, ArrowUp / K / PageUp = previous, Space = play/pause, Esc = close
//   tap or click       : play / pause
//
// YouTube's player swallows touches that land on it, so a transparent layer sits over the video to catch swipes;
// play/pause is sent to the player with postMessage (enablejsapi=1) and its real state is read back the same way.
//
// API: ShortsViewer.open(items, index)   items: [{ id, title, channel, meta }]
(function (root) {
  'use strict';
  const SWIPE_PX = 50;        // minimum vertical travel that counts as a swipe
  const TAP_PX = 10;          // movement under this is a tap
  const COOLDOWN_MS = 450;    // ignore further navigation this soon after the last one (wheel / trackpad bursts)
  const HINT_KEY = 'shortsHintSeen';

  let items = [], idx = 0, isOpen = false, playing = false, pushed = false, lastNav = 0, hintTimer = null;
  let startX = 0, startY = 0, tracking = false;
  const $ = id => document.getElementById(id);

  function embedUrl(id) {
    const v = encodeURIComponent(id);
    return `https://www.youtube.com/embed/${v}?autoplay=1&controls=0&rel=0&modestbranding=1&playsinline=1&loop=1&playlist=${v}&enablejsapi=1&iv_load_policy=3`;
  }
  // Videos are swapped by replacing the iframe element, not by changing its src: every src change adds an entry
  // to the browser's history, so after a few swipes the Back button would step through old videos instead of
  // closing the viewer.
  function onFrameLoad() {
    // learn the player's real state (playing / paused / blocked autoplay) so one tap always does the right thing
    try { $('svFrame').contentWindow.postMessage(JSON.stringify({ event: 'listening', id: 1 }), '*'); } catch { /* ignore */ }
  }
  function loadFrame(url) {
    const old = $('svFrame');
    const f = document.createElement('iframe');
    f.id = 'svFrame';
    f.allow = 'autoplay; encrypted-media; picture-in-picture';
    f.title = 'Short video';
    f.addEventListener('load', onFrameLoad);
    f.src = url;
    old.replaceWith(f);
  }
  function command(func) {
    const f = $('svFrame');
    try { f.contentWindow.postMessage(JSON.stringify({ event: 'command', func, args: [] }), '*'); } catch { /* player not ready */ }
  }
  function flash(text) {
    const b = $('svFlash'); b.textContent = text; b.classList.remove('show'); void b.offsetWidth; b.classList.add('show');
  }
  function togglePlay() {
    if (playing) { command('pauseVideo'); flash('⏸'); } else { command('playVideo'); flash('▶'); }
  }

  function show(i, dir) {
    idx = i;
    const it = items[idx];
    playing = false;
    loadFrame(embedUrl(it.id));
    $('svTitle').textContent = it.title;
    $('svMeta').textContent = `${it.channel} · ${it.meta}`;
    $('svCount').textContent = `${idx + 1} / ${items.length}`;
    $('svYt').href = `https://www.youtube.com/watch?v=${encodeURIComponent(it.id)}`;
    $('svUp').disabled = idx === 0;
    $('svDown').disabled = idx === items.length - 1;
    const stage = $('svStage');
    stage.classList.remove('slide-up', 'slide-down');
    if (dir) { void stage.offsetWidth; stage.classList.add(dir > 0 ? 'slide-up' : 'slide-down'); }
  }

  function go(d) {
    const now = Date.now();
    if (now - lastNav < COOLDOWN_MS) return;
    const n = idx + d;
    if (n < 0 || n >= items.length) {          // already at an end: small bounce so it feels deliberate
      const stage = $('svStage');
      stage.classList.remove('bounce-up', 'bounce-down'); void stage.offsetWidth;
      stage.classList.add(d > 0 ? 'bounce-up' : 'bounce-down');
      flash(d > 0 ? 'Last one' : 'First one');
      lastNav = now;
      return;
    }
    lastNav = now;
    show(n, d);
  }

  function open(list, index) {
    if (!list || !list.length) return;
    items = list; isOpen = true;
    const v = $('shortsViewer');
    v.hidden = false;
    document.body.style.overflow = 'hidden';
    history.pushState({ shorts: 1 }, '');
    pushed = true;
    show(Math.max(0, Math.min(index || 0, items.length - 1)), 0);
    let seen = false;
    try { seen = localStorage.getItem(HINT_KEY) === '1'; localStorage.setItem(HINT_KEY, '1'); } catch { /* storage blocked */ }
    const hint = $('svHint');
    hint.hidden = seen;
    clearTimeout(hintTimer);
    if (!seen) hintTimer = setTimeout(() => { hint.hidden = true; }, 3500);
    $('svStage').focus({ preventScroll: true });
  }

  function cleanup() {
    if (!isOpen) return;
    isOpen = false;
    loadFrame('about:blank');                    // stops playback
    $('shortsViewer').hidden = true;
    document.body.style.overflow = '';
    clearTimeout(hintTimer);
  }
  function close() {
    if (!isOpen) return;
    // pop the history entry we pushed on open; the popstate handler then runs cleanup()
    if (pushed && history.state && history.state.shorts) { pushed = false; history.back(); } else cleanup();
  }

  function wire() {
    const layer = $('svGesture');
    layer.addEventListener('pointerdown', e => {
      tracking = true; startX = e.clientX; startY = e.clientY;
      try { layer.setPointerCapture(e.pointerId); } catch { /* ignore */ }
    });
    layer.addEventListener('pointerup', e => {
      if (!tracking) return;
      tracking = false;
      const dx = e.clientX - startX, dy = e.clientY - startY;
      if (Math.abs(dy) >= SWIPE_PX && Math.abs(dy) > Math.abs(dx)) go(dy < 0 ? 1 : -1);   // finger moves up = next
      else if (Math.abs(dx) < TAP_PX && Math.abs(dy) < TAP_PX) togglePlay();
    });
    layer.addEventListener('pointercancel', () => { tracking = false; });

    $('shortsViewer').addEventListener('wheel', e => {
      e.preventDefault();
      if (Math.abs(e.deltaY) > 8) go(e.deltaY > 0 ? 1 : -1);
    }, { passive: false });

    $('svUp').addEventListener('click', () => go(-1));
    $('svDown').addEventListener('click', () => go(1));
    $('svClose').addEventListener('click', close);
    $('shortsViewer').addEventListener('click', e => { if (e.target === $('shortsViewer')) close(); });  // dark area beside the video

    document.addEventListener('keydown', e => {
      if (!isOpen) return;
      const k = e.key;
      if (k === 'ArrowDown' || k === 'j' || k === 'PageDown') { e.preventDefault(); go(1); }
      else if (k === 'ArrowUp' || k === 'k' || k === 'PageUp') { e.preventDefault(); go(-1); }
      else if (k === ' ') { e.preventDefault(); togglePlay(); }
      else if (k === 'Escape') { e.preventDefault(); close(); }
    });

    window.addEventListener('popstate', () => { pushed = false; cleanup(); });   // browser/phone Back button

    window.addEventListener('message', e => {
      if (typeof e.data !== 'string' || !e.origin.includes('youtube.com')) return;
      try {
        const d = JSON.parse(e.data);
        if (d.event === 'onStateChange') playing = d.info === 1;
        else if (d.event === 'infoDelivery' && d.info && typeof d.info.playerState === 'number') playing = d.info.playerState === 1;
      } catch { /* not a player message */ }
    });
  }

  const api = { open, close, go, _state: () => ({ idx, count: items.length, isOpen }) };
  root.ShortsViewer = api;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wire); else wire();
})(window);
