// Forms of the Hebrew/Greek text itself (passage-facts), placed on the edition's tokens through
// the alignment: refrains, couplet halves, acrostic letters, selah, psalm-heading terms.
// Mirrors bible_song_builder/textforms.py (chapter_marks) and structure.setting_verses.
import { cvC, cvKey, getOr, minOf, maxOf } from './util.js';

export class Marks {
    constructor() {
        this.breaks = new Map();        // cvKey -> Set of extra line starts
        this.halfB = new Map();         // cvKey -> token where half B starts
        this.refrains = new Map();      // cvKey -> [[lo, hi, "<fact id>#<occurrence>", occurrences]]
        this.acrosticRuns = new Map();  // "cv|tok" -> {cv, tok, letter}: a new letter starts here
        this.letters = [];              // [[cv, tok], letter] for every unit
        this.selah = new Map();         // cvKey -> Set of tokens
        this.headingTerms = [];         // fm.ps.* codes in the heading
        this.headingWords = new Map();  // code -> [cv, Set of tokens] of the edition's words, if aligned
    }
}

function span(keys, first, last, al) {
    const out = new Map();
    for (const k of keys) {
        if (first <= k && k <= last) {
            const hit = al.positions(k);
            if (hit) {
                const s = getOr(out, hit[0], () => new Set());
                for (const p of hit[1]) s.add(p);
            }
        }
    }
    return out;
}

/** The first edition token of a span: [cv, token], or null */
function start(keys, first, last, al) {
    const sp = span(keys, first, last, al);
    if (!sp.size) return null;
    const cv = minOf(sp.keys());
    return [cv, minOf(sp.get(cv))];
}

export function chapterMarks(facts, rows, al, chapter, layout) {
    const m = new Marks();
    if (al.kind === 'none' || al.chaptersOff.has(chapter)) return m;
    const keys = [...new Set(rows.flatMap((r) => r.words))].sort();
    if (!keys.length) return m;
    const loKey = keys[0], hiKey = keys[keys.length - 1];
    const chorus = layout.chorus || {};
    const minWords = chorus.min_words ?? 3;
    const useRefrains = ['text', 'both'].includes(chorus.source ?? 'text');
    const minRun = (layout.stanzas || {}).acrostic_min_run ?? 2;
    const here = (cv) => cvC(cv) === chapter;
    // a "refrain" that only introduces speech is no chorus: each time, a quote starts with the next word (textforms.py)
    const quoteStarts = new Set(facts.filter((f) => f.kind === 'quote').map((f) => f.first));
    const skipFrames = chorus.skip_speech_frames ?? true;
    const introducesSpeech = (occ) => occ.length > 0 && occ.every(([, b]) => quoteStarts.has(keys.find((k) => k > b)));

    for (const f of facts) {
        if (f.kind !== 'form' || f.last < loKey || f.first > hiKey) continue;
        const v = f.value || '';
        if (v === 'fm.tx.refrain' && useRefrains && (f.words ?? 0) >= minWords) {
            const occ = f.occurrences || [];
            if (skipFrames && introducesSpeech(occ)) continue;
            occ.forEach(([a, b], i) => {
                // a refrain may run over a verse end; each verse's piece must be long enough by itself
                const perVerse = new Map();
                for (const k of keys) {
                    if (a <= k && k <= b) getOr(perVerse, cvKey(+k.slice(2, 5), +k.slice(5, 8)), () => []).push(k);
                }
                for (const ks of perVerse.values()) {
                    if (new Set(ks.map((k) => k.slice(0, 11))).size < minWords) continue;   // words, not morphemes
                    for (const [cv, pos] of span(ks, ks[0], ks[ks.length - 1], al)) {
                        if (here(cv) && pos.size) {
                            const lo = minOf(pos), hi = maxOf(pos);
                            getOr(m.refrains, cv, () => []).push([lo, hi, `${f.id}#${i + 1}`, occ.length]);
                            const br = getOr(m.breaks, cv, () => new Set());
                            br.add(lo);
                            br.add(hi + 1);
                        }
                    }
                }
            });
        } else if (v === 'fm.tx.halves') {
            const halves = f.halves || [];
            if (halves.length === 2) {
                const s = start(keys, halves[1][0], halves[1][1], al);
                if (s && here(s[0])) m.halfB.set(s[0], s[1]);
            }
        } else if (v === 'fm.tx.acrostic') {
            // runs of the same letter (a unit with no letter belongs to the run before it)
            const runs = [];
            for (const [a, b, letter] of f.letters || []) {
                if (letter && (!runs.length || runs[runs.length - 1][0] !== letter)) runs.push([letter, []]);
                if (runs.length) runs[runs.length - 1][1].push([a, b]);
            }
            const stanzaic = runs.length > 0 && maxOf(runs.map(([, u]) => u.length)) >= minRun;
            for (const [letter, us] of runs) {
                const s = start(keys, us[0][0], us[0][1], al);
                if (s && here(s[0])) {
                    m.letters.push([s, letter]);
                    if (stanzaic) {
                        m.acrosticRuns.set(`${s[0]}|${s[1]}`, { cv: s[0], tok: s[1], letter });
                        getOr(m.breaks, s[0], () => new Set()).add(s[1]);
                    }
                }
            }
        } else if (v === 'fm.ps.selah') {
            for (const [cv, pos] of span(keys, f.first, f.last, al)) {
                if (here(cv)) {
                    const s = getOr(m.selah, cv, () => new Set());
                    for (const p of pos) s.add(p);
                }
            }
        } else if (v.startsWith('fm.ps.') && v !== 'fm.ps.higgayon' && v !== 'fm.ps.halleluyah') {
            const s = start(keys, f.first, f.last, al);
            // heading terms: on the first verse (or the title, which the verse map puts at verse 1)
            if ((s && here(s[0]) && s[0] % 1000 <= 1) || (s === null && +f.first.slice(2, 5) === chapter)) {
                if (!m.headingTerms.includes(v)) {
                    m.headingTerms.push(v);
                    if (s) m.headingWords.set(v, [s[0], span(keys, f.first, f.last, al).get(s[0])]);
                }
            }
        }
    }
    return m;
}

// ---- setting (structure.setting_verses) ----

const SONG_FORMS = ['fm.ms.song'];
const SONG_QUOTES = ['qt.song', 'qt.song_speech'];
const POETIC_FORMS = ['fm.ms.lines', 'fm.ed.lines', 'fm.ed.qlines', 'fm.ed.block', 'fm.tr.poetry'];
const keyCv = (key) => cvKey(+key.slice(2, 5), +key.slice(5, 8));

/** Spine verses set as song and as poetic lines, by passage facts (codes: layout.toml [setting]) */
export function settingVerses(facts, spineVerses, cfg = null) {
    cfg = cfg || {};
    const songForms = new Set(cfg.song_forms ?? SONG_FORMS);
    const songQuotes = new Set(cfg.song_quotes ?? SONG_QUOTES);
    const poeticForms = new Set(cfg.poetic_forms ?? POETIC_FORMS);
    const song = new Set(), poetic = new Set();
    for (const f of facts) {
        const v = f.value;
        if (f.layout === 'list') continue;     // song layout for a list (JOS 12, EST 9), not a song
        const a = keyCv(f.first), b = keyCv(f.last);
        const inside = spineVerses.filter((cv) => a <= cv && cv <= b);
        if ((f.kind === 'form' && songForms.has(v)) || (f.kind === 'quote' && songQuotes.has(v))) inside.forEach((cv) => song.add(cv));
        else if (f.kind === 'form' && poeticForms.has(v)) inside.forEach((cv) => poetic.add(cv));
    }
    return { song, poetic };
}
