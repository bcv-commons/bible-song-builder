// The projection's part of moods: the chapter's style line, the section moods, the credit lines.
// Mirrors bible_song_builder/moods.py (chapter_style, apply_overrides, section_moods,
// source_credits) and plan.edition_moods; the rest of moods.py is half 1 (the plan).
import { ConfigError, cvC, cvKey, fmtCv, pyStr, unique } from './util.js';

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
            if (!(m in (profile.moods || {}))) {
                throw new ConfigError(`${where}: mood '${m}' is not in config/profiles.toml [moods]; `
                    + `choose from ${Object.keys(profile.moods || {}).join(', ')}`);
            }
            out.set(c, new Mood(m, 'manual', where + (src ? ` (the source: ${src.evidence})` : ''), src ? src.instruments : []));
        }
    }
    return out;
}

/** [the chapter's style line, the words its mood added, or null when it keeps the book style] */
export function chapterStyle(profile, mood) {
    if (!mood) return [profile.style, null];
    if (mood.style) return [mood.style, 'its own style line'];
    const words = [...(mood.mood ? [profile.moods[mood.mood] ?? ''] : []),
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
    const sm = (section || []).filter(Boolean);
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
export function sectionMoods(cfg, book, sectionsVerses, moodFacts, modelMoods, toEd, profile) {
    const mc = cfg.toml('moods.toml').section_moods || {};
    if (!(mc.use ?? true)) return sectionsVerses.map(() => null);
    const weights = mc.model_weights ?? [1.0, 0.5, 0.33];
    const spans = [];     // [family, head, Set of edition verses, weight, model, source]
    const edVerses = (runs) => new Set(unrun(runs).map(toEd).filter((e) => e !== null));
    for (const f of moodFacts) spans.push([f.family, f.head, edVerses(f.verses), 1.0, false, 'passage-facts']);
    if (mc.use_model ?? true) {
        for (const r of modelMoods) {
            const ev = edVerses(r.verses);
            r.moods.forEach((m, i) => {
                if (i < weights.length) spans.push([m.family, m.head, ev, weights[i], true, 'passage-moods-model']);
            });
        }
    }
    const families = profile.families || {};
    return sectionsVerses.map((vs) => {
        const V = new Set(vs);
        const score = new Map(), cover = new Map(), why = new Map();
        for (const [fam, head, ev, w, model, src] of spans) {
            const ov = [...ev].filter((e) => V.has(e));
            if (ov.length) {
                score.set(fam, (score.get(fam) || 0) + w * ov.length);
                if (!cover.has(fam)) cover.set(fam, new Set());
                ov.forEach((e) => cover.get(fam).add(e));
                if (!why.has(fam)) why.set(fam, []);
                why.get(fam).push([head, model, `${src} ${book} ${cvs([...ev].sort((a, b) => a - b))}`]);
            }
        }
        let best = null;
        for (const [f, s] of score) {
            if (best === null || s > score.get(best) || (s === score.get(best) && f > best)) best = f;
        }
        if (best === null || cover.get(best).size < (mc.min_share ?? 0.5) * V.size || !families[best]) return null;
        const ws = why.get(best);
        return {
            family: best, head: ws[0][0], tag: profile.family_tag.replace('{words}', families[best]),
            evidence: unique(ws.map((x) => x[2])).join('; '), model: ws.some((x) => x[1]),
        };
    });
}
