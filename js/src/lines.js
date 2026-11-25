// Lyric lines, voices and stanzas for one chapter. Mirrors bible_song_builder/lines.py; see its
// docstring for the rules (each clause line breaks the edition's verse at the earliest edition
// token any of its words aligned to; stanzas at source paragraph ends, acrostic letters, and
// long runs split at the strongest source signals).
import { voiceOf } from './config.js';
import { count, cvC, cvKey, getOr, maxOf, minOf, mostCommon, pyStrip, stripChars, tupleLess, unique, WORD_CHAR, wordRuns } from './util.js';

const OPENING = new Set('“‘"\'([{«‹¿¡—–-');    // default; layout.toml [text] line_start_punctuation

/** Length of a text in words, or in letters for scripts without spaces (layout.toml [text] count) */
export function countUnits(text, mode = 'words') {
    if (mode === 'characters') return (text.match(WORD_CHAR) || []).length;
    return wordRuns(text).length;
}

export const speakerId = (row) => row.speaker_id || row.speaker || null;
export const clauseKey = (row) => row.clause_key || row.first || null;

const speaker = (id, label, voice) => ({ id, label, voice });

function line(cv, text, firstToken, quote, sp, rowSeg, clause = null) {
    return {
        cv, text, first_token: firstToken, quote, speaker: sp, row_seg: rowSeg,
        para_end: false, refrain: null, acrostic: null, selah: false, clause, opening: null,
    };
}

export class Stanza {
    constructor(lines = [], reason = 'start') {
        this.lines = lines;
        // start, acrostic, para, paragraph, split, chorus, midverse
        this.reason = reason;
    }

    get verses() {
        return unique(this.lines.map((ln) => ln.cv)).sort((a, b) => a - b);
    }
}

function rowTargets(row, al) {
    const out = new Map();
    for (const k of row.words) {
        const hit = al.positions(k);
        if (hit) {
            const s = getOr(out, hit[0], () => new Set());
            for (const p of hit[1]) s.add(p);
        }
    }
    return out;
}

/** Move a line start back over the opening punctuation that belongs to it */
function cutStart(text, start, opening) {
    while (start > 0 && opening.has(text[start - 1])) start--;
    return start;
}

function slice(v, starts, opening) {
    const chars = starts.map((t) => cutStart(v.text, v.spans[t][0], opening));
    chars[0] = 0;
    const out = [];
    starts.forEach((t, i) => {
        const end = i + 1 < starts.length ? chars[i + 1] : v.text.length;
        const piece = pyStrip(v.text.slice(chars[i], end));
        if (piece) out.push([t, piece]);
    });
    return out;
}

/** The edition's words at these token positions of a verse (a name, a term), trimmed of the
 *  language's edge words and endings; null if too long (lines.phrase) */
export function phrase(cfg, bt, cv, pos, maxTokens = 6) {
    const v = bt.verses.get(cv);
    if (!v || !v.spans || !pos.size) return null;
    let a = minOf(pos), b = maxOf(pos);
    if (b >= v.spans.length || b - a + 1 > maxTokens) return null;
    const lang = cfg.language(bt.edition.iso);
    const edge = new Set((lang.label_edge_words || []).map((w) => w.toLowerCase()));
    while (a <= b && edge.has(v.tokens[a].toLowerCase())) a++;
    while (b >= a && edge.has(v.tokens[b].toLowerCase())) b--;
    if (a > b) return null;
    let s = v.text.slice(v.spans[a][0], v.spans[b][1]);
    for (const ending of lang.label_strip_endings || []) {
        if (s.endsWith(ending)) {
            s = s.slice(0, s.length - ending.length);
            break;
        }
    }
    s = stripChars(s, ' ,;:.!?“”‘’"');
    return s || null;
}

/** Join a line of fewer than minTokens words to the next line of the same verse and voice, else
 *  to the previous one. A refrain line joins only lines of the same refrain; nothing joins across
 *  the start of an acrostic letter. */
export function mergeShort(lines, minTokens, mode = 'words') {
    const same = (a, b) => a.cv === b.cv && a.quote === b.quote && a.refrain === b.refrain && b.acrostic === null;
    const join = (a, b) => ({ ...a, text: `${a.text} ${b.text}`, para_end: a.para_end || b.para_end, selah: a.selah || b.selah });
    const out = [...lines];
    let i = 0;
    while (i < out.length) {
        const ln = out[i];
        if (countUnits(ln.text, mode) < minTokens) {
            if (i + 1 < out.length && same(ln, out[i + 1])) {
                out[i + 1] = join(ln, out[i + 1]);
                out.splice(i, 1);
                continue;
            }
            if (i > 0 && same(out[i - 1], ln)) {
                out[i - 1] = join(out[i - 1], ln);
                out.splice(i, 1);
                i--;
                continue;
            }
        }
        i++;
    }
    return out;
}

/** speaker_id -> {voice, hits}: where the edition's text names each speaker, once per book
 *  (lines.speaker_hits). hits: [{part, label, n, chapter}] in plan order, part "named" (the
 *  speaker's name) or "described" (the words introducing them), chapter the edition chapter.
 *  refs: the book plan's speakers. */
export function speakerHits(cfg, refs, al, bt) {
    const out = new Map();
    for (const [sid, ref] of Object.entries(refs)) {
        const hits = [];
        for (const part of ['named', 'described']) {
            for (const [keys, n] of ref[part] || []) {
                const perVerse = new Map();
                for (const k of keys) {
                    const hit = al.positions(k);
                    if (hit) {
                        const s = getOr(perVerse, hit[0], () => new Set());
                        for (const p of hit[1]) s.add(p);
                    }
                }
                for (const [cv, pos] of perVerse) {
                    const label = phrase(cfg, bt, cv, pos);
                    if (label) hits.push({ part, label, n, chapter: cvC(cv) });
                }
            }
        }
        out.set(sid, { voice: voiceOf(cfg, sid, ref.voice), hits });
    }
    return out;
}

/** speaker_id -> {id, label, voice} for one edition chapter (lines.speaker_labels). The label is
 *  the commonest of the edition's words naming the speaker in this chapter (named, else described),
 *  else none (the cast table's name is used). So a chapter gets the same label whether the client
 *  has the whole book or only the chapter. chapter null: the commonest in the book (the cast
 *  table). hits: speakerHits(). */
export function speakerLabels(hits, chapter = null) {
    const out = new Map();
    for (const [sid, { voice, hits: hs }] of hits) {
        const pick = (part) => {
            const c = new Map();
            for (const h of hs) if (h.part === part && (chapter === null || h.chapter === chapter)) count(c, h.label, h.n);
            return c.size ? mostCommon(c) : null;
        };
        const label = pick('named') ?? pick('described');
        out.set(sid, speaker(sid, label, voice));
    }
    return out;
}

/** Lyric lines of an edition chapter (lines.build_lines) */
export function buildLines(cfg, bt, chapter, rows, al, speakers, vmapCv, { minTokens = 3, marks, poetry = 'clauses+halves', textCfg = null, pull = false } = {}) {
    textCfg = textCfg || {};
    const own = new Set(textCfg.line_start_punctuation || '');
    const opening = own.size ? own : OPENING;
    const verses = bt.chapterVerses(chapter);
    const breaks = new Map(), owner = new Map(), verseRows = new Map();
    const paraEnds = [];
    for (const r of rows) {
        const targets = al.kind !== 'none' ? rowTargets(r, al) : new Map();
        if (!targets.size) {
            const cv = vmapCv(cvKey(r.chapter, r.verse));
            if (cv !== null) getOr(verseRows, cv, () => []).push(r);
        }
        for (const [cv, pos] of targets) {
            const b = getOr(breaks, cv, () => new Map());
            const lo = minOf(pos);
            if (!b.has(lo)) b.set(lo, r);
            const o = getOr(owner, cv, () => new Map());
            for (const p of pos) if (!o.has(p)) o.set(p, r);
            getOr(verseRows, cv, () => []).push(r);
        }
        if (r.para_end || r.para_end_mam) {
            if (targets.size) {
                const cv = maxOf(targets.keys());
                paraEnds.push([cv, maxOf(targets.get(cv))]);
            } else {
                const cv = vmapCv(cvKey(r.chapter, r.verse));
                if (cv !== null) paraEnds.push([cv, 1e9]);
            }
        }
    }

    // a quote inside a speech ("q00016.t1" inside "q00016") is sung by the outer speaker unless
    // cast-rules.toml says nested_quotes = "inner"
    const outer = (cfg.castRules().nested_quotes ?? 'outer') === 'outer';
    const topSpeaker = new Map();
    for (const r of rows) if (r.quotation && !r.quotation.includes('.')) topSpeaker.set(r.quotation, speakerId(r));

    const voice = (r) => {
        if (!r || !r.quotation) return [null, null];
        let q = r.quotation, sid = speakerId(r);
        if (outer && q.includes('.') && topSpeaker.has(q.split('.')[0])) {
            q = q.split('.')[0];
            sid = topSpeaker.get(q);
        }
        return [q, (sid ? speakers.get(sid) : null) || speaker(sid, null, voiceOf(cfg, sid, null))];
    };

    const lines = [];
    for (const v of verses) {
        const cv = cvKey(v.chapter, v.verse);
        const cand = breaks.get(cv) || new Map();
        if (al.kind === 'none' || v.spans === null || !cand.size) {
            // one line per verse; its voice is the voice of most of the verse's clause lines
            const vr = verseRows.get(cv) || [];
            const byWords = new Map();
            for (const r of vr) count(byWords, r.quotation ?? null, r.words.length);
            const q = byWords.size ? mostCommon(byWords) : null;
            const r0 = vr.find((r) => (r.quotation ?? null) === q) ?? null;
            const [qq, sp] = voice(r0);
            lines.push(line(cv, v.text, 0, qq, sp, r0 ? r0.seg : null));
        } else {
            let base = new Set(cand.keys());
            const hb = marks.halfB.get(cv);
            if (hb !== undefined && poetry !== 'clauses') base = poetry === 'halves' ? new Set([hb]) : new Set([...base, hb]);
            for (const t of marks.breaks.get(cv) || []) base.add(t);
            let starts = unique([0, ...[...base].filter((t) => t < v.tokens.length)]).sort((a, b) => a - b);
            // pull: a clause's line start moves back over the unaligned words before it (compact alignments)
            const moved = new Map();
            if (pull) {
                const own = owner.get(cv) || new Map();
                const fixed = new Set([...(marks.breaks.get(cv) || []), ...(hb !== undefined ? [hb] : [])]);
                const next = [];
                for (const t of starts) {
                    let s = t;
                    if (cand.has(t) && !fixed.has(t)) {
                        const lo = next.length ? next[next.length - 1] : -1;
                        while (s - 1 > lo && !own.has(s - 1) && !pyStrip(v.text.slice(v.spans[s - 1][1], v.spans[s][0]))) s--;
                    }
                    next.push(s);
                    moved.set(s, t);
                }
                starts = next;
            }
            let prevRow = null;
            const first = lines.length;
            for (const [t, piece] of slice(v, starts, opening)) {
                const r = cand.get(moved.has(t) ? moved.get(t) : t) || (owner.get(cv) || new Map()).get(t) || prevRow;
                prevRow = r;
                const [qq, sp] = voice(r);
                lines.push(line(cv, piece, t, qq, sp, r ? r.seg : null, r ? clauseKey(r) : null));
            }
            mark(lines.slice(first), cv, v.tokens.length, marks);
        }
        setOpening(lines, cv, verseRows.get(cv) || []);
        for (const [pcv, ptok] of paraEnds) {
            if (pcv === cv) {
                let idx = -1;
                lines.forEach((ln, i) => { if (ln.cv === cv && ln.first_token <= ptok) idx = i; });
                if (idx < 0) idx = lines.length - 1;
                lines[idx].para_end = true;
            }
        }
    }
    return mergeShort(lines, minTokens, textCfg.count || 'words');
}

/** Give the verse's first line the keys of the clauses that open the verse in the source */
function setOpening(lines, cv, vrows) {
    const first = lines.find((ln) => ln.cv === cv);
    if (!first || !vrows.length) return;
    const rows = [...vrows].sort((a, b) => a.chapter - b.chapter || a.verse - b.verse || a.seg - b.seg || (a.line || 1) - (b.line || 1));
    const keys = [clauseKey(rows[0])];
    const top = rows.find((r) => !r.depth);
    if (top !== undefined) keys.push(clauseKey(top));
    first.opening = unique(keys).filter(Boolean);
}

/** Flag the lines of one verse: refrain, acrostic letter start, selah */
function mark(vlines, cv, nTokens, marks) {
    vlines.forEach((ln, k) => {
        const end = (k + 1 < vlines.length ? vlines[k + 1].first_token : nTokens) - 1;
        let best = -1;
        for (const [lo, hi, rid, n] of marks.refrains.get(cv) || []) {
            if (lo <= ln.first_token && end <= hi && n > best) {
                ln.refrain = rid;
                best = n;
            }
        }
        for (const { cv: mcv, tok, letter } of marks.acrosticRuns.values()) {
            if (mcv === cv && ln.first_token === tok) ln.acrostic = letter;
        }
        if ([...(marks.selah.get(cv) || [])].some((t) => ln.first_token <= t && t <= end)) ln.selah = true;
    });
}

// How strongly the source marks a new start at a verse, read from the clause that opens it
// (clause-connectives `link`, clause-columns `line` and `part_switch`).
const SOURCE_BREAK = [
    ['link', { episode: 3, and_now: 1, development: 1, time: 1 }],
    ['line', { setting: 1 }],
    ['part_switch', { switch: 1 }],
];
const VOICE_CHANGE = 1;
const STANZA_COST = 2;

export function breakStrength(ln, prev, signals, bt, weights = null) {
    let score = 0;
    const keysAll = ln.opening && ln.opening.length ? ln.opening : [ln.clause];
    for (const [field, table] of SOURCE_BREAK) {
        let vals = keysAll.filter(Boolean).map((k) => (signals[k] || {})[field]);
        if (field === 'part_switch') {    // a new participant counts in narration, not inside speech
            vals = vals.map((v, i) => [keysAll[i], v]).filter(([k]) => (signals[k || ''] || {}).line !== 'speech').map(([, v]) => v);
        }
        score += vals.length ? Math.max(...vals.map((v) => table[v] ?? 0)) : 0;
    }
    if ((ln.quote === null) !== (prev.quote === null)) score += VOICE_CHANGE;
    const w = weights || {};
    if (bt.headingBefore.has(ln.cv)) score += w.edition_heading_weight ?? 0;
    if (bt.paragraphStarts.has(ln.cv)) score += w.edition_paragraph_weight ?? 0;
    return score;
}

/** Stanzas (lines.stanzas) */
export function stanzas(lines, bt, maxLines, signals = null, cfg = null, isNt = false) {
    cfg = cfg || {};
    signals = signals || {};
    const reason = new Map();
    const setdefault = (i, r) => { if (!reason.has(i)) reason.set(i, r); };
    lines.forEach((ln, i) => { if (ln.para_end) setdefault(i + 1, 'para'); });
    const startsVerse = lines.map((ln, i) => i).filter((i) => i === 0 || lines[i].cv !== lines[i - 1].cv);
    const edPar = cfg.edition_paragraphs ?? 'never';
    if (edPar === 'always' || (edPar === 'nt' && isNt)) {
        for (const i of startsVerse) if (bt.paragraphStarts.has(lines[i].cv)) setdefault(i, 'paragraph');
    }
    lines.forEach((ln, i) => { if (ln.acrostic) reason.set(i, 'acrostic'); });
    const cuts = [...reason.keys()].filter((c) => c > 0 && c < lines.length).sort((a, b) => a - b);
    const bounds = [0, ...cuts, lines.length];
    const chunks = bounds.slice(1).map((b, k) => [bounds[k], b]).filter(([a, b]) => b > a);
    const strength = new Map(startsVerse.filter((i) => i).map((i) => [i, breakStrength(lines[i], lines[i - 1], signals, bt, cfg)]));
    const minLines = cfg.min_lines ?? 2;

    const split = (a, b) => {
        if (b - a <= maxLines) return [[a, b]];
        const cand = startsVerse.filter((i) => a + minLines <= i && i <= b - minLines);
        const pts = [a, ...cand, b];
        // best[j]: [cost, largest piece]; each stanza costs STANZA_COST, each split earns its strength
        const best = pts.map(() => null);
        const back = pts.map(() => 0);
        best[0] = [0, 0];
        for (let j = 1; j < pts.length; j++) {
            for (let i = 0; i < j; i++) {
                const size = pts[j] - pts[i];
                if (size > maxLines || best[i] === null) continue;
                const [cost, mx] = best[i];
                const c = [cost + STANZA_COST - (i ? strength.get(pts[i]) ?? 0 : 0), Math.max(mx, size)];
                if (best[j] === null || tupleLess(c, best[j])) {
                    best[j] = c;
                    back[j] = i;
                }
            }
        }
        if (best[best.length - 1] === null) return [[a, b]];    // no verse start to cut at
        const out = [];
        let j = pts.length - 1;
        while (j) {
            out.push([pts[back[j]], pts[j]]);
            j = back[j];
        }
        return out.reverse();
    };

    const out = [];
    for (const [a, b] of chunks) {
        for (const [x, y] of split(a, b)) out.push(new Stanza(lines.slice(x, y), x ? reason.get(x) ?? 'split' : 'start'));
    }
    return out;
}
