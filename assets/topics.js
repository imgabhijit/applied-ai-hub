// Topic extraction for the Topics tab: finds what the videos in a time window are
// "about" by counting 1-3 word phrases in their titles. Pure functions, no DOM:
// loaded by the pages as window.HubTopics and by Node for testing
// (node scripts/test_topics.js).
//
//   1. clean   - drop emojis, the channel's own name, URLs; keep tokens like gpt-6, 5.5
//   2. tokens  - lowercase words; stopwords/clickbait filler are skipped
//   3. n-grams - 1-3 word phrases that do not start or end with a stopword
//   4. count   - per VIDEO (a phrase counts once per title) and per CHANNEL
//                (so one channel's multi-part series cannot fake a trend)
//   5. compare - the window's rate against the whole data set's rate: a phrase that is
//                suddenly frequent is "rising"; one that is always frequent is not
//   6. merge   - variants of one topic ("openai dots", "chatgpt dots", "dots") collapse
(function (root) {
  'use strict';

  const STOP = new Set((
    // common English
    'a an the and or but if then else of to in on at by for with without from into onto over under up down out off ' +
    'is are was were be been being am do does did done doing have has had having it its this that these those they them their ' +
    'i me my mine we our ours you your yours he him his she her hers who whom whose which what when where why how ' +
    'not no nor so than too very can could should would will shall may might must just only also even still yet already ' +
    'about above after again against all any both each few more most other some such own same here there now ' +
    'get got gets getting make makes made making use uses used using want wants need needs know knows ' +
    'one two three four five six seven eight nine ten first last next new old ' +
    // video-title filler / clickbait
    'insane crazy amazing incredible unbelievable ridiculous absurd huge massive mind blowing blowing wild ' +
    'best worst better top ultimate complete full free paid cheap easy simple quick fast faster fastest ' +
    'tutorial guide course masterclass beginner beginners explained explain explains explaining review reviews tested testing test ' +
    'step steps tips tricks hack hacks secret secrets truth honest brutally everything anything something nothing ' +
    'finally officially official released release announced announcement dropped drops introducing meet ' +
    'live stream episode part day week month year today tonight ' +
    'watch video videos shorts short thing things way ways reason reasons ' +
    'vs versus like love really actually literally basically totally completely ' +
    'update updates updated news latest breaking happened happening change changes changed changing ' +
    'here\'s it\'s that\'s don\'t doesn\'t isn\'t you\'re i\'m i\'ve we\'re let\'s what\'s ' +
    'every many much lot lots another people everyone anyone ' +
    'let build builds built building create creates created creating work works working ' +
    'start started starting stop go going gone goes see look looking come comes take takes ' +
    'real big small little long short high low good bad great ' +
    'learn learning show shows showing explore exploring ' +
    'dont doesnt isnt youre im ive were lets whats thats its'
  ).split(/\s+/).filter(Boolean));

  // Words that are the hub's own subject: too generic to be a topic by themselves.
  const GENERIC = new Set(('ai artificial intelligence agent agents agentic model models llm llms tool tools app apps ' +
    'automation automate workflow workflows prompt prompts code coding developer developers software tech technology ' +
    'business money project projects system systems platform data cloud api apis oracle').split(/\s+/));

  // Ordinary words that are never a topic on their own or at the edge of a phrase. The data also teaches the
  // code more (see commonWords), but only for words it sees often enough.
  const COMMON_EXTRA = new Set(('understand understanding understood game games gave give gives given run runs ran running multiple ' +
    'price prices pricing cost costs decision decisions life lives money time times years people world future history story stories ' +
    'mistake mistakes problem problems solution solutions plan plans rule rules lesson lessons result results case cases example examples ' +
    'idea ideas answer answers question questions skill skills career careers job jobs find found finds put set sets keep keeps ' +
    'call calls turn turns bring brings ask asks try tries tried move moves play plays feel feels think thinks thought ' +
    'changer changers game-changer winner winners loser losers killer killers beat beats beating win wins lose ' +
    'user users customer customers client clients team teams company companies product products service services ' +
    'content creator creators channel channels youtube twitter reddit ' +
    'demo demos overview introduction intro basics session sessions webinar podcast interview keynote highlights recap summary roundup series ' +
    'stuff hours minutes seconds days weeks months ago later soon again always never maybe ' +
    'right wrong true false real fake smart smarter dumb stupid hard harder easier powerful power strong stronger weak ' +
    'cut cuts replace replaced replacing kill killed ruin ruined fix fixed fixes break broke broken save saved saves ' +
    'turns turned stay stays remember forget forgot learn learned lost found mind brain eyes').split(/\s+/).filter(Boolean));

  const EMOJI = /[\u{1F000}-\u{1FFFF}\u{2190}-\u{2BFF}\u{FE0F}\u{200D}]/gu;

  function clean(title, channel) {
    let t = String(title || '');
    if (channel) {
      // "... | Oracle Developers" style suffixes
      const c = channel.trim().toLowerCase();
      if (c.length > 2) t = t.replace(new RegExp(c.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi'), ' ');
    }
    return t.replace(/https?:\/\/\S+/g, ' ').replace(/&amp;|&#39;|&quot;/g, ' ').replace(EMOJI, ' ');
  }

  // [{ t: 'gpt-6', raw: 'GPT-6' }, ...]: t is the counting key (lowercase, possessive removed), raw keeps casing.
  function tokenize(title) {
    const out = [];
    const re = /[A-Za-z0-9][A-Za-z0-9.+#'\u2019-]*/g;
    let m;
    while ((m = re.exec(title))) {
      const whole = m[0].replace(/[.'\u2019-]+$/, '');
      if (!whole) continue;
      // "GPT-6" -> GPT, 6 so it matches "GPT 6"; other hyphens ("no-code") stay inside the word
      for (const raw of whole.split(/-(?=\d)|(?<=\d)-/)) {
        if (!raw) continue;
        out.push({ t: raw.toLowerCase().replace(/\u2019/g, "'").replace(/'s$/, ''), raw });
      }
    }
    return out;
  }

  const isNum = t => /^\d+(\.\d+)?$/.test(t);
  const isStop = t => STOP.has(t) || /^(19|20)\d\d$/.test(t) || (isNum(t) && t.length > 4);

  // Ordinary English words, learned from the data itself. A name ("Opus", "Dots", "Muse") is capitalised even
  // in the middle of a sentence-case title; a plain word ("understand", "price") is not. Words with too little
  // evidence are left alone.
  const commonCache = new WeakMap();
  function commonWords(videos) {
    if (!videos) return new Set(COMMON_EXTRA);
    if (commonCache.has(videos)) return commonCache.get(videos);
    const seen = new Map(); // t -> [capitalised, total] in sentence-case titles, not the first word
    for (const v of videos) {
      const toks = tokenize(clean(v.title, v.channel_name));
      const alpha = toks.filter(x => /^[A-Za-z]{4,}$/.test(x.raw) && !STOP.has(x.t));
      if (alpha.length < 3) continue;
      const caps = alpha.filter(x => x.raw[0] === x.raw[0].toUpperCase()).length;
      if (caps / alpha.length > 0.6) continue;               // Title Case title: capitalisation says nothing
      toks.forEach((x, i) => {
        if (i === 0 || !/^[A-Za-z]{3,}$/.test(x.raw)) return;
        const e = seen.get(x.t) || [0, 0];
        e[1]++; if (x.raw[0] === x.raw[0].toUpperCase()) e[0]++;
        seen.set(x.t, e);
      });
    }
    const common = new Set(COMMON_EXTRA);
    for (const [t, [c, n]] of seen) if (n >= 4 && c / n < 0.25) common.add(t);
    commonCache.set(videos, common);
    return common;
  }

  // The counting key of a phrase typed by a person (used for the rules file): lowercase content words, sorted.
  function keyOf(phrase) {
    const content = tokenize(clean(phrase)).map(x => x.t).filter(t => !isStop(t));
    return content.length === 1 ? content[0] : [...content].sort().join(' ');
  }

  // data/topic_rules.json (all optional):
  //   ignore_words:  words that may never be a topic or sit at the edge of one
  //   ignore_topics: phrases to hide
  //   aliases:       { "variant phrase": "canonical phrase" } - merge their counts
  function normalizeRules(r) {
    r = r || {};
    const alias = new Map();
    for (const [from, to] of Object.entries(r.aliases || {})) {
      const a = keyOf(from), b = keyOf(to);
      if (a && b && a !== b) alias.set(a, { key: b, text: String(to) });
    }
    return {
      ignoreWords: new Set((r.ignore_words || []).map(w => String(w).toLowerCase())),
      ignoreTopics: new Set((r.ignore_topics || []).map(keyOf).filter(Boolean)),
      alias,
    };
  }

  // Distinct topic candidates of one title as Map(key -> display text).
  // 1-word keys are the word; 2-3 word keys are the sorted content words, so "muse from meta"
  // and "meta's muse" are the same key.
  function ngrams(title, channel, common, alias) {
    common = common || COMMON_EXTRA;
    const toks = tokenize(clean(title, channel));
    const out = new Map();
    for (let n = 1; n <= 3; n++) {
      for (let i = 0; i + n <= toks.length; i++) {
        const w = toks.slice(i, i + n);
        const first = w[0].t, last = w[n - 1].t;
        if (isStop(first) || isStop(last) || common.has(first) || common.has(last)) continue;
        if (n === 1) {
          if (first.length < 3 || isNum(first) || GENERIC.has(first)) continue;
        } else if (w.every(x => GENERIC.has(x.t) || isNum(x.t) || isStop(x.t))) continue;
        let bad = false; // a phrase may contain one stopword inside ("state of art") but not two in a row
        for (let k = 1; k < n; k++) if (isStop(w[k].t) && isStop(w[k - 1].t)) bad = true;
        if (bad) continue;
        const content = w.filter(x => !isStop(x.t)).map(x => x.t);
        if (n > 1 && (content.length < 2 || new Set(content).size < content.length)) continue;
        const key = n === 1 ? first : [...content].sort().join(' ');
        const al = alias && alias.get(key);
        const k2 = al ? al.key : key;
        if (!out.has(k2)) out.set(k2, al ? al.text : w.map(x => x.raw).join(' '));
      }
    }
    return out;
  }

  // Counts for a list of videos: Map(key -> {key, videos, channels:Set, views, forms:Map, ids})
  function count(videos, common, alias) {
    const stats = new Map();
    for (const v of videos) {
      for (const [key, form] of ngrams(v.title, v.channel_name, common, alias)) {
        let s = stats.get(key);
        if (!s) stats.set(key, (s = { key, videos: 0, channels: new Set(), views: 0, forms: new Map(), ids: [] }));
        s.videos++; s.channels.add(v.channel_id); s.views += v.view_count || 0;
        s.forms.set(form, (s.forms.get(form) || 0) + 1);
        s.ids.push(v.video_id);
      }
    }
    return stats;
  }

  function display(s) {
    // prefer a mixed-case surface form ("OpenAI Dots") over ALL CAPS or all lower
    let best = null, bestScore = -1;
    for (const [form, n] of s.forms) {
      const mixed = form !== form.toUpperCase() && form !== form.toLowerCase() ? 1 : 0;
      const score = mixed * 1000 + n;
      if (score > bestScore) { best = form; bestScore = score; }
    }
    return best.replace(/['\u2019]s\b/g, '');
  }

  /**
   * videos:    the videos inside the window (after the page's filters)
   * baseline:  all videos for the same filters, any age (used for the "rising" ratio and word statistics)
   * opts: { windowDays, baselineDays, minChannels, vocab, rules }  (vocab: stable array used to learn common words;
   *        rules: parsed data/topic_rules.json)
   */
  function topics(videos, baseline, opts) {
    opts = Object.assign({ windowDays: 7, baselineDays: 90, minChannels: 2 }, opts);
    const rules = normalizeRules(opts.rules);
    const learned = commonWords(opts.vocab || baseline || videos);
    const common = rules.ignoreWords.size ? new Set([...learned, ...rules.ignoreWords]) : learned;
    const win = count(videos, common, rules.alias);
    const base = baseline && baseline.length ? count(baseline, common, rules.alias) : new Map();
    const wDays = Math.max(opts.windowDays, 1), bDays = Math.max(opts.baselineDays, wDays);
    // With no meaningful 'before' period (window ~ all the data) novelty cannot be measured: rank by mentions only.
    const hasBaseline = bDays - wDays >= 14;

    const cands = [];
    for (const s of win.values()) {
      if (rules.ignoreTopics.has(s.key)) continue;
      const words = s.key.split(' ');
      // a lone word needs wider support than a phrase: one-word "topics" are the noisiest
      if (s.channels.size < (words.length === 1 ? Math.max(opts.minChannels, 3) : opts.minChannels)) continue;
      const rateW = s.videos / wDays;
      const b = base.get(s.key);
      const bVideos = Math.max((b ? b.videos : 0) - s.videos, 0); // baseline without the window itself
      const rateB = bVideos / Math.max(bDays - wDays, 1);
      const burst = hasBaseline ? (rateW + 0.02) / (rateB + 0.02) : 1;
      cands.push({
        key: s.key, words, label: display(s), n: words.length, videos: s.videos, channels: s.channels.size,
        views: s.views, burst, isNew: hasBaseline && (bVideos === 0 || burst >= 4), ids: s.ids, _set: new Set(s.ids),
        // Rising: breadth first, boosted by novelty.   Mentions: breadth, then volume.
        rising: s.channels.size * Math.log2(1 + burst) + 0.15 * Math.log10(1 + s.views),
        mentions: s.channels.size * 100 + s.videos + Math.log10(1 + s.views),
      });
    }

    // Merge: a longer phrase whose videos are almost all covered by a shorter phrase it contains is a variant of that
    // topic. It goes to the most specific such parent (fewest videos).
    cands.sort((a, b) => a.n - b.n || b.videos - a.videos);
    const kept = [];
    for (const c of cands) {
      let parent = null;
      for (const k of kept) {
        if (k.n >= c.n || !k.words.every(w => c.words.includes(w))) continue;
        let overlap = 0; for (const id of c._set) if (k._set.has(id)) overlap++;
        if (overlap / c._set.size >= 0.9 && (!parent || k.videos < parent.videos)) parent = k;
      }
      if (parent) (parent.variants = parent.variants || []).push(c); else kept.push(c);
    }
    for (const k of kept) {
      if (!k.variants) continue;
      // if a longer variant carries most of the topic, it is the better label ("Claude Mods" for "Mods")
      const best = k.variants.filter(v => v.videos >= 0.6 * k.videos).sort((a, b) => b.videos - a.videos || b.n - a.n)[0];
      if (best) k.label = best.label;
      k.variants = k.variants.sort((a, b) => b.videos - a.videos).map(v => v.label).filter(l => l !== k.label).slice(0, 3);
    }
    return kept;
  }

  function rank(list, mode, limit) {
    const key = mode === 'mentions' ? 'mentions' : 'rising';
    return [...list].sort((a, b) => b[key] - a[key]).slice(0, limit || 30);
  }

  const api = { topics, rank, ngrams, tokenize, clean, commonWords, keyOf, normalizeRules };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.HubTopics = api;
})(typeof window !== 'undefined' ? window : globalThis);
