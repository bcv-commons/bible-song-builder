// The projection's part of moods: the chapter's style line, the section moods, the credit lines.
// Mirrors bible_song_builder/moods.py (chapter_style, apply_overrides, section_moods,
// source_credits) and plan.edition_moods; the rest of moods.py is half 1 (the plan).
import { phrase } from './lines.js';
import { ConfigError, count, cvC, cvKey, fmtCv, mostCommon, pySplit, pyStr, unique } from './util.js';

export class Mood {
    constructor(mood, basis, evidence, instruments = [], style = null) {
        this.mood = mood;              // e.g. "lament"; null = only an instrument
        this.basis = basis;            // heading, song, type, purpose, commentary, delivery, manual
        this.evidence = evidence;      // what in the source gave it
        this.instruments = instruments;
        this.style = style;            // a whole style line set by hand (books/<BOOK>.toml)
    }
}

/** Edition chapter -> the plan's chapter mood (a spine chapter goes where its middle verse goes) */
export function editionMoods(bookPlan, toEd) {
    const out = new Map();
    for (const m of bookPlan.moods) {
        const e = toEd(cvKey(m.mid[0], m.mid[1]));
        if (e !== null) out.set(cvC(e), new Mood(m.mood, m.basis, m.evidence, [...m.instruments]));
    }
    return out;
}

/** The [chapters.N] blocks of config/books/<BOOK>.toml laid over the source's moods */
export function applyOverrides(cfg, book, found, profile) {
    const out = new Map(found);
    for (const [n, ch] of Object.entries(cfg.book(book).chapters || {})) {
        const c = parseInt(n, 10);
        const src = found.get(c);
        const where = `config/books/${book}.toml [chapters.${c}]`;
        if ('style' in ch) {
            out.set(c, new Mood(src ? src.mood : null, 'manual', where, [], ch.style));
        } else if ('mood' in ch) {
            const m = ch.mood;
            if (!m) {
                out.delete(c);
                continue;
            }
            const ml = moodList(cfg);
            const known = unique([...Object.keys(profile.moods || {}), ...Object.keys(ml.kinds), ...Object.keys(ml.moods)]);
            if (!known.includes(m)) {
                throw new ConfigError(`${where}: mood '${m}' is not a kind of config/mood-list.toml [kinds] or `
                    + 'config/profiles.toml [moods], nor a mood of the list; '
                    + `choose from ${known.join(', ')}`);
            }
            out.set(c, new Mood(m, 'manual', where + (src ? ` (the source: ${src.evidence})` : ''), src ? src.instruments : []));
        }
    }
    return out;
}

/** config/mood-list.toml, checked: [kinds] and [families] name moods of the list, and each mood
 *  has words and a known energy. moods.mood_list */
export function moodList(cfg) {
    const ml = cfg.toml('mood-list.toml');
    const where = 'config/mood-list.toml';
    const ms = ml.moods || {};
    for (const table of ['kinds', 'families', 'families_of_god']) {
        const bad = Object.entries(ml[table] || {}).filter(([, v]) => v && !(v in ms)).map(([k, v]) => `${k} = '${v}'`).sort();
        if (bad.length) {
            throw new ConfigError(`${where} [${table}]: ${bad.join(', ')}: not a mood of the list; choose from ${Object.keys(ms).join(', ')}`);
        }
    }
    for (const [mid, m] of Object.entries(ms)) {
        if (!m.words || !(m.energy in (ml.energy || {}))) {
            throw new ConfigError(`${where} [moods.${mid}]: needs words, and an energy from [energy] (${Object.keys(ml.energy || {}).join(', ')})`);
        }
    }
    return { use: {}, kinds: {}, families: {}, families_of_god: {}, energy: {}, ...ml };
}

/** The first n of a mood's words for the music service. moods.mood_words */
const moodWords = (ml, mid, n) => ml.moods[mid].words.split(',').slice(0, n).map((w) => w.trim()).join(', ');

/** The words a chapter of this kind adds to the style: the profile's own (profiles.toml [moods])
 *  where it has the kind, else those of its mood in the list, with the mood's usual energy. moods.kind_words */
function kindWords(cfg, profile, kind) {
    if (kind in (profile.moods || {})) return profile.moods[kind];
    const ml = moodList(cfg);
    const mid = ml.kinds[kind] || (kind in ml.moods ? kind : '');
    if (!mid) return '';
    const energy = ml.energy[ml.moods[mid].energy];
    return [moodWords(ml, mid, ml.use.style_words ?? 2), energy].filter(Boolean).join(', ');
}

/** [the chapter's style line, the words its mood added, or null when it keeps the book style] */
export function chapterStyle(cfg, profile, mood) {
    if (!mood) return [profile.style, null];
    if (mood.style) return [mood.style, 'its own style line'];
    const words = [...(mood.mood ? [kindWords(cfg, profile, mood.mood)] : []),
        ...mood.instruments.map((i) => profile.instruments[i] ?? '')].filter(Boolean);
    if (!words.length) return [profile.style, null];
    const added = words.join(', ');
    return [`${profile.base_style}, ${added}${profile.suffix}`, added];
}

// The scholarly sources a mood can come from: the name in the evidence -> passage-facts sources.tsv id
const SOURCES = [['Tyndale Open Study Notes', 'tyndale'], ['Scriptura', 'scriptura']];

/** The credit each source of the chapter's mood and its section moods asks for.
 *  pins: the plan's dataset pins; sources: the plan's sources.tsv credits. */
export function sourceCredits(mood, section, pins, sources) {
    const out = [];
    const ds = (name, what) => `${what}: bcv-commons/${name} ${pyStr(pins[name].tag)}, ${pins[name].licence}`;
    if (mood && mood.evidence.includes('Hebrew commentators')) {
        out.push(ds('hebrew-commentary-terms', 'what the Hebrew commentators call the psalm')
            + ' (commentaries from Sefaria, https://www.sefaria.org, Public Domain or CC0)');
        if (mood.evidence.includes('(model-read)')) out.push(ds('hebrew-commentary-terms-model', 'their statements read by a model'));
    }
    let sm = (section || []).filter(Boolean);
    const spans = sm.filter((m) => m.evidence.includes('passage-mood-spans-model'));
    if ((mood && mood.evidence.includes('passage-mood-spans-model')) || spans.length) out.push(ds('passage-mood-spans-model', 'moods read by two models'));
    sm = sm.filter((m) => !spans.includes(m));
    if (sm.length) {
        out.push('section moods: bcv-commons/passage-facts mood families (UBS dictionaries SDBH and Louw-Nida, CC BY-SA 4.0)');
        if (sm.some((m) => m.model)) out.push(ds('passage-moods-model', 'section moods read by a model'));
    }
    if (!mood) return out;
    return [...SOURCES.filter(([name, sid]) => mood.evidence.includes(name) && sid in sources).map(([, sid]) => sources[sid]), ...out];
}

/** Spine verses from runs [chapter, first, last] */
export const unrun = (rs) => rs.flatMap(([c, a, b]) => Array.from({ length: b - a + 1 }, (_, i) => cvKey(c, a + i)));

function cvs(vs) {
    const a = vs[0], b = vs[vs.length - 1];
    if (a === b) return fmtCv(a);
    return cvC(a) === cvC(b) ? `${fmtCv(a)}-${b % 1000}` : `${fmtCv(a)}-${fmtCv(b)}`;
}

/** A feeling for each section, where the Hebrew/Greek words of most of its verses mark one
 *  (the plan's mood_facts by rule, model_moods read by a model). Rules: moods.toml [section_moods]. */
export function sectionMoods(cfg, book, sectionsVerses, moodFacts, modelMoods, toEd, profile, words = null) {
    const mc = cfg.toml('moods.toml').section_moods || {};
    if (!(mc.use ?? true)) return sectionsVerses.map(() => null);
    const weights = mc.model_weights ?? [1.0, 0.5, 0.33];
    const ml = moodList(cfg);
    const nWords = ml.use.tag_words ?? 1;
    // the mood of the list a span gives; a family without one counts as itself, "~md.*", and gives no tag
    const moodOf = (m) => (m.of_god ? ml.families_of_god[m.family] : '') || ml.families[m.family] || `~${m.family}`;
    const spans = [];     // [mood, family, head, Set of edition verses, weight, model, source]
    const edVerses = (runs) => new Set(unrun(runs).map(toEd).filter((e) => e !== null));
    for (const f of moodFacts) spans.push([moodOf(f), f.family, f.head, edVerses(f.verses), 1.0, false, 'passage-facts']);
    if (mc.use_model ?? true) {
        for (const r of modelMoods) {
            const ev = edVerses(r.verses);
            r.moods.forEach((m, i) => {
                if (i < weights.length) spans.push([moodOf(m), m.family, m.head, ev, weights[i], true, 'passage-moods-model']);
            });
        }
    }
    return sectionsVerses.map((vs) => {
        const V = new Set(vs);
        const score = new Map(), cover = new Map(), why = new Map();
        for (const [mid, fam, head, ev, w, model, src] of spans) {
            const ov = [...ev].filter((e) => V.has(e));
            if (ov.length) {
                score.set(mid, (score.get(mid) || 0) + w * ov.length);
                if (!cover.has(mid)) cover.set(mid, new Set());
                ov.forEach((e) => cover.get(mid).add(e));
                if (!why.has(mid)) why.set(mid, []);
                why.get(mid).push([fam, head, model, `${src} ${book} ${cvs([...ev].sort((a, b) => a - b))}`]);
            }
        }
        let best = null;
        for (const [m, s] of score) {
            if (best === null || s > score.get(best) || (s === score.get(best) && m > best)) best = m;
        }
        if (best === null || best.startsWith('~') || cover.get(best).size < (mc.min_share ?? 0.5) * V.size) return null;
        const ws = why.get(best);
        return {
            mood: best, hebrew: ml.moods[best].hebrew,
            family: ws[0][0], head: ws[0][1], tag: profile.family_tag.replace('{words}', moodWords(ml, best, nWords)),
            evidence: unique(ws.map((x) => x[3])).join('; '), model: ws.some((x) => x[2]),
            word: (words && words.get(best)) ?? null,
        };
    });
}

/** moods.toml [mood_spans], with its defaults (moods.span_config) */
export function spanConfig(cfg) {
    return {
        use: true, sections: ['spans', 'words'], passes: ['a', 'b'], disagree: 0.5, strength_weights: [1.0, 2.0, 3.0],
        min_marked: 0.3, min_share: 0.5, words_per_change: 100, min_changes: 2, max_changes: 8,
        chapter_reading: 'fill', reading_disagree: 'first', ...(cfg.toml('moods.toml').mood_spans || {}),
    };
}

/** The chapter moods with the reading's (the book plan's readings) laid in, as moods.toml
 *  [mood_spans] chapter_reading says (moods.with_readings). found: editionMoods(). */
export function withReadings(cfg, found, readings, toEd) {
    const c = spanConfig(cfg);
    const how = c.chapter_reading;
    if (!c.use || how === 'off') return found;
    const ml = moodList(cfg);
    const out = new Map(found);
    const first = c.passes.length ? c.passes[0] : 'a';
    for (const r of readings || []) {
        if (r.pass !== first || !(r.mood in ml.moods)) continue;
        if (!r.agree && c.passes.length > 1 && c.reading_disagree === 'none') continue;
        const e = toEd(cvKey(r.mid[0], r.mid[1]));
        if (e === null) continue;
        const old = out.get(cvC(e));
        if (how === 'fill' && old && (old.mood || old.style)) continue;
        const ev = `passage-mood-spans-model pass ${r.pass}: ${r.mood} ${ml.moods[r.mood].hebrew}`
            + (r.because ? ` “${r.because}”` : '') + (r.agree ? '' : ' (the passes differ)') + ' (model-read)';
        out.set(cvC(e), new Mood(r.mood, 'reading', ev, old ? old.instruments : []));
    }
    return out;
}

/** A mood for each section from the span reading (the plan's moodSpans), or null when the chapter
 *  has no spans of the passes used (moods.span_section_moods). sections: per section, its lyric
 *  lines as [the plan row that starts the line, its sung words]; rows: the chapter plan's rows. */
export function spanSectionMoods(cfg, book, sections, rows, spans, profile, words = null) {
    const c = spanConfig(cfg);
    const passes = c.passes;
    if (!c.use) return null;
    const at = new Map();
    rows.forEach((r, i) => { for (const w of r.words || []) at.set(w, i); });
    const idx = new Map(rows.map((r, i) => [r, i]));
    const ranged = [];
    for (const sp of spans || []) {
        if (passes.includes(sp.pass) && at.has(sp.first) && at.has(sp.last)) ranged.push([at.get(sp.first), at.get(sp.last), sp]);
    }
    if (!ranged.length) return null;
    const ml = moodList(cfg);
    const nWords = ml.use.tag_words ?? 1;
    const sw = c.strength_weights;
    const maxW = Math.max(...sw);
    const inner = (i, p) => {
        let best = null;
        for (const x of ranged) if (x[2].pass === p && x[0] <= i && i <= x[1] && (best === null || x[1] - x[0] < best[1] - best[0])) best = x;
        return best ? best[2] : null;
    };
    const raw = [];
    let total = 0;
    for (const lines of sections) {
        const score = new Map(), used = new Map();
        let nAll = 0, marked = 0;
        for (const [row, n] of lines) {
            nAll += n;
            const i = row !== null && row !== undefined ? idx.get(row) : undefined;
            if (i === undefined) continue;
            for (const p of passes) {
                const sp = inner(i, p);
                if (sp && sp.mood in ml.moods) {
                    const m = sp.mood;
                    marked += n;
                    score.set(m, (score.get(m) || 0) + n * sw[sp.strength - 1] * (sp.agree ? 1.0 : c.disagree));
                    if (!used.has(m)) used.set(m, []);
                    if (!used.get(m).includes(sp)) used.get(m).push(sp);
                }
            }
        }
        total += nAll;
        let best = null;
        for (const [m, v] of score) if (best === null || v > score.get(best) || (v === score.get(best) && m > best)) best = m;
        let sum = 0;
        for (const v of score.values()) sum += v;
        if (best === null || marked < c.min_marked * nAll * passes.length || score.get(best) < c.min_share * sum) {
            raw.push([null, 0.0, []]);
            continue;
        }
        raw.push([best, score.get(best) / Math.max(nAll * maxW * passes.length, 1), used.get(best)]);
    }
    const ms = raw.map((x) => x[0]);
    const limit = Math.max(c.min_changes, Math.min(c.max_changes, Math.ceil(total / c.words_per_change)));
    const changes = (xs) => {
        const out = [];
        let cur = null;
        xs.forEach((m, i) => { if (m && m !== cur) { out.push(i); cur = m; } });
        return out;
    };
    for (let ch = changes(ms); ch.length > limit; ch = changes(ms)) {
        let i = null;
        for (const k of ch.slice(1)) if (i === null || raw[k][1] < raw[i][1] || (raw[k][1] === raw[i][1] && k > i)) i = k;
        const m = ms[i];
        for (let j = i; j < ms.length && (ms[j] === m || ms[j] === null); j++) if (ms[j] === m) ms[j] = null;
    }
    return raw.map(([, , usedBest], k) => {
        const m = ms[k];
        if (!m) return null;
        const byWhere = new Map();
        for (const sp of usedBest) {
            if (!sp.verses.length) continue;
            const w = cvs(unrun(sp.verses));
            if (!byWhere.has(w)) byWhere.set(w, []);
            byWhere.get(w).push(sp);
        }
        const where = [...byWhere].slice(0, 2).map(([w, xs]) => `passage-mood-spans-model ${book} ${w} (pass ${unique(xs.map((x) => x.pass)).join(', ')})`
            + (xs[0].because ? ` “${xs[0].because}”` : '')).join('; ');
        const mood = ml.moods[m];
        return {
            mood: m, hebrew: mood.hebrew, family: mood.family ?? '', head: mood.hebrew,
            tag: profile.family_tag.replace('{words}', moodWords(ml, m, nWords)),
            evidence: where, model: true, word: (words && words.get(m)) ?? null,
        };
    });
}

/** Mood of the list -> the edition's most common rendering in this book of the word naming it
 *  (mood-list.toml strong / greek), through the alignment; one-word renderings are preferred.
 *  lexemes: lexemeKeys(). moods.family_words */
export function familyWords(cfg, lexemes, al, bt, testament) {
    const prefix = testament === 'nt' ? 'G' : 'H';
    const out = new Map();
    const ml = moodList(cfg);
    for (const [mid, mood] of Object.entries(ml.moods)) {
        const strongs = [mood.strong || '', mood.greek || ''];
        const one = new Map(), more = new Map();
        for (const s of strongs) {
            if (s.slice(0, 1) !== prefix) continue;
            for (const k of lexemes.get(parseInt(s.slice(1), 10)) || []) {
                const hit = al.positions(k);
                const w = hit ? phrase(cfg, bt, hit[0], hit[1], 3) : null;
                if (w) count(pySplit(w).length === 1 ? one : more, w);
            }
        }
        if (one.size || more.size) out.set(mid, mostCommon(one.size ? one : more));
    }
    return out;
}
