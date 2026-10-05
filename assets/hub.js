// Shared page logic for every Applied AI Hub section page.
// Each page defines window.HUB_PAGE = { slug, title, hasArticles, watch: [{name, site}] }.
// The Home page has slug 'all' plus `sections`: it merges every section's videos and posts.
// All text from data/*.json is untrusted: it only reaches the DOM through esc().
(() => {
  const PAGE = window.HUB_PAGE;
  const DAY = 86400;
  const TIME_WINDOWS = { '1d': DAY, '3d': 3 * DAY, '7d': 7 * DAY, '30d': 30 * DAY, '90d': 90 * DAY };
  const PAGE_SIZE = 24;
  const TRENDING_MIN_SUBS = 5000;
  const IS_HOME = PAGE.slug === 'all';
  const SECTION_LABEL = Object.fromEntries((PAGE.sections || []).map(s => [s.slug, `${s.icon} ${s.title}`]));

  const params = new URLSearchParams(location.search);
  const state = {
    tab:      params.get('tab')  || 'all',
    time:     params.get('time') || '7d',
    // Home mixes huge and tiny channels, so raw views would bury everything but the biggest.
    sort:     params.get('sort') || (PAGE.slug === 'all' ? 'trending' : 'views'),
    layer:    params.get('layer') || 'all',
    lang:     'all',
    section:  'all',
    minViews: 0,
    duration: 'all',
    search:   '',
    channel:  null,
  };
  let videos = [], posts = [], lastUpdated = null;

  const $ = id => document.getElementById(id);

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
  function safeUrl(u) { return /^https?:\/\//i.test(u || '') ? u : '#'; }
  const now = () => Date.now() / 1000;

  function fmtViews(n) {
    if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
    return String(n || 0);
  }
  function fmtAgo(ts) {
    const d = Math.floor(now() - ts);
    if (d < 60) return d + 's ago';
    if (d < 3600) return Math.floor(d / 60) + 'm ago';
    if (d < DAY) return Math.floor(d / 3600) + 'h ago';
    return Math.floor(d / DAY) + 'd ago';
  }
  function fmtDuration(sec) {
    if (!sec) return '';
    const m = Math.floor(sec / 60), s = sec % 60;
    return m >= 60
      ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')}:${String(s).padStart(2, '0')}`
      : `${m}:${String(s).padStart(2, '0')}`;
  }
  function median(nums) {
    if (!nums.length) return 0;
    const a = [...nums].sort((x, y) => x - y), mid = Math.floor(a.length / 2);
    return a.length % 2 ? a[mid] : (a[mid - 1] + a[mid]) / 2;
  }

  // One section's items, or on Home every section's, each tagged with its section.
  function collect(data) {
    const slugs = IS_HOME ? PAGE.sections.map(s => s.slug) : [PAGE.slug];
    return slugs.flatMap(slug => (data[slug] || []).map(x => ({ ...x, _section: slug })));
  }

  // ── filtering & sorting ────────────────────────────────────────────────────
  function matchesDuration(d) {
    switch (state.duration) {
      case 'over3':  return d > 180;
      case '3to15':  return d >= 180 && d < 900;
      case '15to30': return d >= 900 && d < 1800;
      case '30to60': return d >= 1800 && d < 3600;
      case 'long':   return d >= 3600;
      default:       return true;
    }
  }
  function sortVideos(list) {
    const t = now();
    const hours = v => Math.max(1, (t - v.timestamp) / 3600);
    const key = {
      views:    v => v.view_count,
      velocity: v => v.view_count / hours(v),
      // Views relative to channel size; the floor stops a 17-subscriber channel with 92 views
      // from outranking everything.
      trending: v => v.view_count / Math.max(v.subscribers || 0, TRENDING_MIN_SUBS),
      newest:   v => v.timestamp,
    }[state.sort] || (v => v.view_count);
    return [...list].sort((a, b) => key(b) - key(a));
  }
  function filteredVideos() {
    const since = now() - (TIME_WINDOWS[state.time] || 7 * DAY);
    const q = state.search.toLowerCase();
    return sortVideos(videos.filter(v =>
      v.timestamp >= since &&
      v.live_broadcast !== 'live' &&
      (state.layer === 'all' || v.layer === state.layer) &&
      (state.lang === 'all' || v.language === state.lang) &&
      (state.section === 'all' || v._section === state.section) &&
      v.view_count >= state.minViews &&
      matchesDuration(v.duration || 0) &&
      (!q || v.title.toLowerCase().includes(q) || v.channel_name.toLowerCase().includes(q))));
  }

  // ── rendering ─────────────────────────────────────────────────────────────
  function empty(title, sub) {
    return `<div class="empty-state"><h3>${esc(title)}</h3><p>${esc(sub)}</p></div>`;
  }
  function cardHtml(v, rank, hidden) {
    const dur = fmtDuration(v.duration);
    return `<div class="video-card${hidden ? ' hidden' : ''}" data-id="${esc(v.video_id)}" data-ch="${esc(v.channel_name)}" data-title="${esc(v.title)}">
      <div class="thumb-wrap"><img src="${esc(v.thumbnail)}" alt="" loading="lazy" data-vid="${esc(v.video_id)}">
        <span class="rank-badge">#${rank}</span>${dur ? `<span class="duration-badge">${dur}</span>` : ''}
        <button class="newtab-btn" title="Open in new tab">↗</button></div>
      <div class="card-body"><div class="card-channel"><span>${esc(v.channel_name)}</span><span class="card-layer">${esc(IS_HOME ? (SECTION_LABEL[v._section] || v.layer) : v.layer)}</span></div>
        <div class="card-title">${esc(v.title)}</div>
        <div class="card-meta"><span class="card-views">👁 ${fmtViews(v.view_count)}</span><span>${fmtAgo(v.timestamp)}</span></div></div></div>`;
  }
  function gridHtml(list, gridId) {
    const cards = list.map((v, i) => cardHtml(v, i + 1, i >= PAGE_SIZE)).join('');
    const more = list.length > PAGE_SIZE
      ? `<div class="show-more-wrap" data-more-for="${gridId}"><button class="btn" data-act="more">${list.length - PAGE_SIZE} more</button></div>` : '';
    return `<div class="video-grid" id="${gridId}">${cards}</div>${more}`;
  }

  function renderAll() {
    const list = filteredVideos();
    $('panel-all').innerHTML = list.length
      ? `<p class="section-label">Top ${list.length} videos · ${esc(state.time)}</p>${gridHtml(list, 'allGrid')}`
      : empty('No videos match', 'Try a wider time window or clear a filter.');
  }

  function renderChannels() {
    const list = filteredVideos();
    const by = {};
    list.forEach(v => (by[v.channel_name] = by[v.channel_name] || []).push(v));
    const panel = $('panel-channels');

    if (state.channel) {
      const vids = by[state.channel] || [];
      panel.innerHTML = `<div class="detail-header"><button class="btn" data-act="back">← Back</button>
        <span class="name">${esc(state.channel)}</span><span class="count">${vids.length} videos</span></div>`
        + (vids.length ? gridHtml(vids, 'chGrid') : empty('Nothing in this window', 'Try a wider time window.'));
      return;
    }
    const stats = Object.entries(by)
      .map(([name, vs]) => ({ name, med: median(vs.map(v => v.view_count)), n: vs.length }))
      .sort((a, b) => b.med - a.med);
    panel.innerHTML = stats.length
      ? `<p class="section-label">${stats.length} channels with uploads · ${esc(state.time)}</p><div class="channel-card-grid">${
          stats.map(c => `<div class="channel-card" data-channel="${esc(c.name)}"><div class="channel-card-name">${esc(c.name)}</div>
            <div class="channel-card-views">📊 ${fmtViews(c.med)} median</div>
            <div class="channel-card-count">${c.n} video${c.n !== 1 ? 's' : ''}</div></div>`).join('')}</div>`
      : empty('No channel data', 'Try a wider time window.');
  }

  function renderArticles() {
    if (!PAGE.hasArticles) return;
    const q = state.search.toLowerCase();
    const list = posts.filter(p =>
      (state.layer === 'all' || p.layer === state.layer) &&
      (state.section === 'all' || p._section === state.section) &&
      (!q || p.title.toLowerCase().includes(q) || p.source.toLowerCase().includes(q)));
    const items = list.length
      ? `<div class="post-list">${list.map(p => `<a class="post" href="${esc(safeUrl(p.link))}" target="_blank" rel="noopener noreferrer">
          <div class="post-title">${esc(p.title)}</div><div class="post-meta">${esc(p.source)} · ${esc(p.layer)} · ${fmtAgo(p.timestamp)}</div></a>`).join('')}</div>`
      : empty('No recent posts', 'Written feeds are checked on every refresh and show the last 14 days.');
    const watch = (PAGE.watch || []).length
      ? `<p class="watch-note">No RSS feed - check these pages directly:</p><div class="watch-list">${
          PAGE.watch.map(w => `<a href="${esc(safeUrl(w.site))}" target="_blank" rel="noopener noreferrer">${esc(w.name)} ↗</a>`).join('')}</div>` : '';
    $('panel-articles').innerHTML = `<p class="section-label">Articles &amp; releases</p>${items}${watch}`;
  }

  function render() {
    renderAll(); renderChannels(); renderArticles();
    const channels = new Set(videos.map(v => v.channel_id)).size;
    $('metaInfo').textContent = `Refreshed: ${lastUpdated ? fmtAgo(new Date(lastUpdated).getTime() / 1000) : 'never'} | ${videos.length} videos · ${channels} channels`;
  }

  // ── controls ──────────────────────────────────────────────────────────────
  function syncToolbar() {
    $('timeSelect').value = state.time;
    $('sortSelect').value = state.sort;
    $('layerSelect').value = state.layer;
    $('langSelect').value = state.lang;
    if (IS_HOME) $('sectionSelect').value = state.section;
    $('viewsSelect').value = String(state.minViews);
    $('durationSelect').value = state.duration;
    // Video-only filters make no sense on the Articles tab.
    document.querySelectorAll('[data-video-only]').forEach(el => {
      el.style.display = state.tab === 'articles' ? 'none' : '';
    });
  }
  function updateUrl() {
    history.replaceState(null, '', `?tab=${state.tab}&time=${state.time}&sort=${state.sort}&layer=${encodeURIComponent(state.layer)}`);
  }
  function switchTab(name) {
    if (name === 'articles' && !PAGE.hasArticles) name = 'all';
    state.tab = name; state.channel = null;
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
    document.querySelectorAll('.panel').forEach(p => p.classList.toggle('active', p.id === 'panel-' + name));
    syncToolbar(); render(); updateUrl();
  }
  function bind(id, key, parse = x => x) {
    $(id).addEventListener('change', e => { state[key] = parse(e.target.value); state.channel = null; render(); updateUrl(); });
  }

  // ── player ────────────────────────────────────────────────────────────────
  function openPlayer(id, channel) {
    $('creditBar').textContent = channel ? 'Source: ' + channel : '';
    $('playerFrame').src = `https://www.youtube.com/embed/${encodeURIComponent(id)}?autoplay=1&rel=0&modestbranding=1&playsinline=1`;
    $('playerModal').classList.add('open');
    document.body.style.overflow = 'hidden';
  }
  function closePlayer() {
    $('playerModal').classList.remove('open');
    $('playerFrame').src = '';
    document.body.style.overflow = '';
  }
  function toast(msg, ms = 3500) {
    const t = $('toast'); t.textContent = msg; t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), ms);
  }

  document.addEventListener('click', e => {
    const t = e.target;
    const newtab = t.closest('.newtab-btn');
    if (newtab) {
      e.stopPropagation();
      const c = newtab.closest('.video-card');
      window.open(`player.html?v=${encodeURIComponent(c.dataset.id)}&t=${encodeURIComponent(c.dataset.title)}&c=${encodeURIComponent(c.dataset.ch)}`, '_blank', 'noopener');
      return;
    }
    const card = t.closest('.video-card');
    if (card) { openPlayer(card.dataset.id, card.dataset.ch); return; }
    const chCard = t.closest('.channel-card');
    if (chCard) { state.channel = chCard.dataset.channel; renderChannels(); return; }
    const act = t.closest('[data-act]');
    if (act && act.dataset.act === 'back') { state.channel = null; renderChannels(); }
    if (act && act.dataset.act === 'more') {
      const wrap = act.closest('.show-more-wrap');
      document.querySelectorAll(`#${wrap.dataset.moreFor} .video-card.hidden`).forEach(c => c.classList.remove('hidden'));
      wrap.remove();
    }
    if (t === $('playerModal')) closePlayer();
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closePlayer(); });
  // Fall back to a smaller thumbnail if the high-res one is missing.
  document.addEventListener('error', e => {
    const img = e.target;
    if (img.tagName === 'IMG' && img.dataset.vid && !img.dataset.fell) {
      img.dataset.fell = '1';
      img.src = `https://i.ytimg.com/vi/${img.dataset.vid}/mqdefault.jpg`;
    }
  }, true);

  window.addEventListener('DOMContentLoaded', async () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.addEventListener('click', () => switchTab(b.dataset.tab)));
    $('closeBtn').addEventListener('click', closePlayer);
    bind('timeSelect', 'time'); bind('sortSelect', 'sort'); bind('layerSelect', 'layer'); bind('langSelect', 'lang');
    if (IS_HOME) bind('sectionSelect', 'section');
    bind('viewsSelect', 'minViews', Number); bind('durationSelect', 'duration');
    $('searchInput').addEventListener('input', e => { state.search = e.target.value.trim(); state.channel = null; render(); });
    $('navSelect').addEventListener('change', e => { if (e.target.value) location.href = e.target.value; });
    switchTab(state.tab);

    try {
      const res = await fetch('data/videos.json');
      const data = await res.json();
      videos = collect(data);
      lastUpdated = data.last_updated;
    } catch { toast('Could not load video data.'); }
    try {
      const res = await fetch('data/posts.json');
      posts = collect(await res.json()).sort((a, b) => b.timestamp - a.timestamp);
    } catch { /* posts.json is optional until the first written-feed run */ }
    render();
  });

  if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js');
})();
