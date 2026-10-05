// Prints the top topics for a section and window from the real data:
//   node scripts/test_topics.js agents 7
const fs = require('fs');
const T = require('../assets/topics.js');
const [section = 'agents', days = '7', mode = 'rising'] = process.argv.slice(2);
const data = JSON.parse(fs.readFileSync(__dirname + '/../data/videos.json', 'utf8'));
const all = section === 'all'
  ? Object.keys(data).filter(k => Array.isArray(data[k])).flatMap(k => data[k])
  : data[section];
const now = Date.now() / 1000;
const win = all.filter(v => v.timestamp >= now - days * 86400 && v.live_broadcast !== 'live');
const list = T.rank(T.topics(win, all, { windowDays: +days, baselineDays: 90 }), mode, 25);
console.log(`${section} / ${days}d: ${win.length} videos, mode=${mode}`);
for (const t of list) {
  console.log(`${t.isNew ? '↑' : ' '} ${t.label.padEnd(30)} ch=${String(t.channels).padStart(2)} vid=${String(t.videos).padStart(3)} views=${String(Math.round(t.views / 1000)).padStart(5)}K burst=${t.burst.toFixed(1)}${t.variants && t.variants.length ? '  also: ' + t.variants.join(', ') : ''}`);
}
