// Smoke test for the Topics tab, run by the refresh workflow after each data update:
//   node scripts/check_topics.js
// Fails (exit 1) if topic extraction throws, is far too slow, or returns nothing for a
// section/window that has plenty of videos - i.e. if a data-format or code change broke the tab.
// It does not judge topic *quality*; tune that in data/topic_rules.json.
const fs = require('fs');
const path = require('path');
const T = require('../assets/topics.js');

const read = f => JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'data', f), 'utf8'));
const data = read('videos.json');
let rules = {};
try { rules = read('topic_rules.json'); } catch (e) { console.log('(no valid topic_rules.json - using defaults)', e.message); }

const sections = Object.keys(data).filter(k => Array.isArray(data[k]));
const scopes = { ...Object.fromEntries(sections.map(k => [k, data[k]])), all: sections.flatMap(k => data[k]) };
const now = Date.now() / 1000;
let failures = 0;

for (const [name, all] of Object.entries(scopes)) {
  for (const days of [7, 30]) {
    const win = all.filter(v => v.timestamp >= now - days * 86400 && v.live_broadcast !== 'live');
    const t0 = Date.now();
    let list;
    try {
      list = T.rank(T.topics(win, all, { windowDays: days, baselineDays: 90, vocab: all, minChannels: days >= 30 ? 3 : 2, rules }), 'rising', 30);
    } catch (e) {
      console.log(`FAIL ${name}/${days}d: threw ${e.message}`); failures++; continue;
    }
    const ms = Date.now() - t0;
    const problems = [];
    if (win.length >= 100 && list.length === 0) problems.push('no topics from ' + win.length + ' videos');
    if (ms > 15000) problems.push('too slow: ' + ms + 'ms');
    if (list.some(t => !t.label || !(t.channels >= 1))) problems.push('malformed topic');
    console.log(`${problems.length ? 'FAIL' : 'ok  '} ${name.padEnd(12)} ${String(days).padStart(2)}d  ${String(win.length).padStart(5)} videos -> ${String(list.length).padStart(2)} topics  ${String(ms).padStart(4)}ms  ${list.slice(0, 3).map(t => t.label).join(' | ')}${problems.length ? '   <- ' + problems.join('; ') : ''}`);
    failures += problems.length ? 1 : 0;
  }
}
if (failures) { console.log(`\n${failures} check(s) failed`); process.exit(1); }
console.log('\nAll topic checks passed');
