// Unit tests for the Topics tokenizer/ranker (assets/topics.js) on SYNTHETIC titles, so they are deterministic and
// run in the GitHub Action without any data:   node scripts/test_topics_unit.js
// They exist because multi-word topics once silently disappeared (every phrase was folded into a one-word parent).
const T = require('../assets/topics.js');
let failed = 0;
const ok = (cond, name, detail = '') => { console.log(`${cond ? 'PASS' : 'FAIL'} ${name}${detail ? '  ' + detail : ''}`); if (!cond) failed++; };

// -- helpers --------------------------------------------------------------------------------------------------
let n = 0;
const vid = (title, ch, views = 1000, ageDays = 1) =>
  ({ video_id: 'v' + (n++), title, channel_id: ch, channel_name: 'Chan ' + ch, view_count: views, timestamp: Date.now() / 1000 - ageDays * 86400 });
const labels = list => list.map(t => t.label);
const find = (list, text) => list.find(t => t.label.toLowerCase() === text.toLowerCase() || (t.variants || []).some(v => v.toLowerCase() === text.toLowerCase()));
const top = (list, text) => list.find(t => t.label.toLowerCase() === text.toLowerCase());   // top-level topics only, not variants
const run = (videos, opts = {}) => T.topics(videos, opts.baseline || videos, { windowDays: 7, baselineDays: 90, minChannels: 2, ...opts });

// -- tokenizing -----------------------------------------------------------------------------------------------
const tk = s => T.tokenize(s).map(x => x.t).join('|');
ok(tk('GPT-6.1 Sol') === 'gpt|6.1|sol', 'GPT-6.1 splits at the hyphen next to a digit', tk('GPT-6.1 Sol'));
ok(tk("Meta's Muse") === 'meta|muse', 'possessive is removed from the key', tk("Meta's Muse"));
ok(tk('no-code tools') === 'no-code|tools', 'other hyphens stay inside a word');
const segs = T.tokenize('OpenAI Dots, GPT-6.1 Sol: Is it good?').map(x => x.seg).join('');
ok(segs === '00111222', 'clauses are numbered at commas and colons', segs);

// -- phrases ----------------------------------------------------------------------------------------------------
const phrases = t => [...T.ngrams(t, '').values()];
ok(phrases('Gemini 4 Argon explained').includes('Gemini 4 Argon'), '3-word model name is a phrase');
ok(!phrases('AI agents and automation tools').some(p => /^AI agents$/i.test(p)), 'a phrase made only of generic words is not a topic', JSON.stringify(phrases('AI agents and automation tools')));
ok(phrases('Oracle Fusion AI Agent Studio tutorial').some(p => p.split(' ').length === 4), '4-word phrases are generated');
ok(!phrases('Dots, GPT-6.1 Sol').some(p => /Dots GPT/.test(p)), 'phrases do not cross a comma', JSON.stringify(phrases('Dots, GPT-6.1 Sol')));
ok(!phrases('Sonnet 5.5 is 30 percent faster').some(p => /Is 30/i.test(p)), 'no phrase with "is" inside');
ok(phrases('The Muse from Meta is here').some(p => p === 'Muse from Meta'), 'a preposition may sit inside a phrase');
ok(!phrases('6 Astra things').some(p => p.startsWith('6 ')), 'a phrase never starts with a bare number');
const k1 = [...T.ngrams('Muse from Meta', '').keys()].find(k => k.includes('muse') && k.includes('meta'));
const k2 = [...T.ngrams("Meta's Muse", '').keys()].find(k => k.includes('muse') && k.includes('meta'));
ok(k1 && k1 === k2, 'word order and possessive do not split a topic', `${k1} / ${k2}`);
ok([...T.ngrams('MCP Servers', '').keys()].includes([...T.ngrams('MCP Server', '').keys()].find(k => /mcp server/.test(k))), 'plural and singular share a key');

// -- ranking: multi-word topics survive --------------------------------------------------------------------------
const claude = [
  ...['a', 'b', 'c', 'd'].map(c => vid('Claude Code tips for ' + c, c)),
  ...['e', 'f', 'g'].map(c => vid('Claude Opus 5.5 is here ' + c, c)),
  ...['h', 'i', 'j', 'k', 'l'].map(c => vid('My Claude workflow ' + c, c)),
];
// "Claude" is long-established (plenty of older videos), so its phrases must stay topics of their own
const older = Array.from({ length: 60 }, (_, i) => vid('Claude workflow and Claude Code ' + i, 'o' + (i % 12), 1000, 30 + (i % 50)));
const r1 = run(claude, { baseline: [...claude, ...older] });
ok(top(r1, 'Claude Code'), '"Claude Code" is its own top-level topic, not swallowed by "Claude"', labels(r1).join(', '));
ok(top(r1, 'Claude Opus 5.5') || top(r1, 'Opus 5.5'), 'a model-version phrase is its own topic', labels(r1).join(', '));
ok(top(r1, 'Claude'), 'the generic brand word is still a topic', labels(r1).join(', '));
// ...and with no history at all (everything is new) the phrases may fold into the word instead: that is the intended behaviour
const r1b = run(claude);
ok(find(r1b, 'Claude Code'), 'with no history the phrase is still reachable', labels(r1b).join(', '));

// a long-established word keeps its phrases; a brand-new word folds them in
const base = [...claude, ...Array.from({ length: 40 }, (_, i) => vid('Claude Code and more ' + i, 'x' + (i % 8), 1000, 40 + i % 30))];
const withDots = [
  vid('OpenAI Dots is wild', 'a'), vid('OpenAI Dots review', 'b'), vid('ChatGPT Dots setup', 'c'), vid('ChatGPT Dots tips', 'd'), vid('Dots changes everything', 'e'),
];
const r2 = run(withDots, { baseline: [...base, ...withDots], windowDays: 7 });
const dots = find(r2, 'Dots');
ok(dots && /dots/i.test(dots.label), 'a brand-new word is the topic by itself', labels(r2).join(', '));
ok(dots && (dots.variants || []).some(v => /OpenAI Dots|ChatGPT Dots/.test(v)) || (dots && /OpenAI Dots|ChatGPT Dots/.test(dots.label)), 'and its phrases fold into it', JSON.stringify(dots && dots.variants));
ok(r2.filter(t => /dots/i.test(t.label)).length === 1, 'no duplicate "Dots" topics', labels(r2).join(', '));

// fragments: "Astra" only ever appears inside "GPT 6 Astra"
const astra = ['a', 'b', 'c', 'd', 'e'].map(c => vid('GPT-6 Astra review ' + c, c));
const r3 = run(astra);
ok(find(r3, 'GPT 6 Astra') && !r3.some(t => t.label === 'Astra'), 'the longer phrase replaces its fragments', labels(r3).join(', '));

// a single channel cannot create a topic
const spam = Array.from({ length: 8 }, (_, i) => vid('Zorblax part ' + i, 'solo'));
ok(!run(spam).some(t => /zorblax/i.test(t.label)), 'one channel repeating a word is not a topic');
ok(run([vid('Zorblax one', 'a'), vid('Zorblax two', 'b')]).every(t => !/zorblax/i.test(t.label)), 'a lone word needs 3 channels, a phrase needs 2');

// filler words never become topics
const filler = ['a', 'b', 'c', 'd'].map(c => vid('INSANE new tutorial you must watch ' + c, c));
ok(run(filler).length === 0, 'filler words do not form topics', labels(run(filler)).join(', '));

// -- rules file --------------------------------------------------------------------------------------------------
const rv = ['a', 'b', 'c', 'd'].map(c => vid('Grok Bot and GrokBot for ' + c, c));
const rg = ['a', 'b', 'c', 'd'].map(c => vid('Grok Bot review ' + c, c));
const merged = run(rv, { rules: { aliases: { 'grokbot': 'Grok Bot' } } });
ok(merged.filter(t => /grok/i.test(t.label)).length === 1, 'aliases merge spellings into one topic', labels(merged).join(', '));
ok(!run(rv, { rules: { ignore_topics: ['grok bot'] } }).some(t => /^grok bot$/i.test(t.label)), 'ignore_topics hides a phrase');
ok(run(rg).some(t => /grok/i.test(t.label)) && !run(rg, { rules: { ignore_words: ['grok'] } }).some(t => /grok/i.test(t.label)), 'ignore_words removes a word everywhere');

// -- ranking modes -----------------------------------------------------------------------------------------------
const old = Array.from({ length: 60 }, (_, i) => vid('Claude Code workflow ' + i, 'o' + (i % 12), 1000, 30 + (i % 50)));
const recent = [...['a', 'b', 'c'].map(c => vid('Claude Code workflow ' + c, c)), ...['d', 'e', 'f', 'g'].map(c => vid('Zenith agent launch ' + c, c))];
const rr = T.topics(recent, [...old, ...recent], { windowDays: 7, baselineDays: 90, minChannels: 2 });
const best = T.rank(rr, 'rising', 3)[0];
ok(best && /zenith/i.test(best.label), 'Rising puts a new term above an always-popular one', best && best.label);
const hasBase = T.topics(recent, recent, { windowDays: 90, baselineDays: 90, minChannels: 2 });
ok(hasBase.every(t => !t.isNew), 'a 90-day window (no "before") marks nothing as rising');

console.log(failed ? `\n${failed} unit test(s) failed` : '\nAll topic unit tests passed');
process.exit(failed ? 1 : 0);
