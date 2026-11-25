// Lyric lines, voices and stanzas for one chapter. Mirrors bible_song_builder/lines.py; see its
// docstring for the rules (each clause line breaks the edition's verse at the earliest edition
// token any of its words aligned to; stanzas at source paragraph ends, acrostic letters, and
// long runs split at the strongest source signals).
import { voiceOf } from './config.js';
import { BOOKS, count, cvC, isPySpace, cvKey, getOr, maxOf, minOf, mostCommon, pyStrip, stripChars, tupleLess, unique, WORD_CHAR, wordRuns } from './util.js';

const OPENING = new Set('“‘"\'([{«‹¿¡—–-');    // line_start "list": default of layout.toml [text] line_start_punctuation
const CLAUSE_END = new Set('.,;:!?…。，、；：！？');   // default of layout.toml [text] clause_end_punctuation
const WORD = /^[\p{L}\p{N}\p{M}]$/u;
const OPENS = /^[\p{Ps}\p{Pi}]$/u;

/** Length of a text in words, or in letters for scripts without spaces (layout.toml [text] count) */
export function countUnits(text, mode = 'words') {
    if (mode === 'characters') return (text.match(WORD_CHAR) || []).length;
    return wordRuns(text).length;
}

export const speakerId = (row) => row.speaker_id || row.speaker || null;
export const clauseKey = (row) => row.clause_key || row.first || null;

const speaker = (id, label, voice) => ({ id, label, voice });

function line(cv, text, firstToken, quote, sp, rowSeg, clause = null, row = null) {
    return {
        cv, text, first_token: firstToken, quote, speaker: sp, row_seg: rowSeg,
        para_end: false, refrain: null, acrostic: null, selah: false, clause, opening: null,
        row,                                  // the plan row that starts the line
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

/** Move a line start back over the punctuation before its first word that belongs to it (lines._cut_start) */
function cutStart(text, start, [kind, marks]) {
    if (kind === 'list') {
        while (start > 0 && marks.has(text[start - 1])) start--;
        return start;
    }
    const isWord = (c) => WORD.test(c);
    let j = start;
    while (j > 0 && !isPySpace(text[j - 1]) && !isWord(text[j - 1])) j--;
    if (j > 0 && isWord(text[j - 1])) {          // between two words with no space: split at a clause end
        let last = -1;
        for (let i = j; i < start; i++) if (marks.has(text[i])) last = i;
        return last >= 0 ? last + 1 : start;
    }
    let s = j;
    for (;;) {
        let i = s;
        while (i > 0 && isPySpace(text[i - 1])) i--;
        if (i === s || i === 0) return s;
        let r = i;
        while (r > 0 && !isPySpace(text[r - 1]) && !isWord(text[r - 1])) r--;
        const run = [...text.slice(r, i)];
        if (!run.length || (r > 0 && !isPySpace(text[r - 1])) || run.some((c) => marks.has(c)) || !run.every((c) => OPENS.test(c))) return s;
        s = r;
    }
}

/** layout.toml [text] line_start: ['spacing', clause end marks] or ['list', opening marks] (lines.line_start_rule) */
export function lineStartRule(textCfg) {
    if ((textCfg.line_start ?? 'spacing') === 'list') {
        const own = new Set(textCfg.line_start_punctuation || '');
        return ['list', own.size ? own : OPENING];
    }
    const own = new Set(textCfg.clause_end_punctuation || '');
    return ['spacing', own.size ? own : CLAUSE_END];
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
    const sp = cfg.layout(bt.edition).speakers || {};
    const stops = new Set(sp.label_stops ?? [':', ';', '—', '–', '«', '“', '"']);
    for (let k = a; k < b; k++) {       // a name ends where the text speaks (lines.phrase)
        if ([...v.text.slice(v.spans[k][1], v.spans[k + 1][0])].some((ch) => stops.has(ch))) {
            let last = null;
            for (const p of pos) if (a <= p && p <= k && (last === null || p > last)) last = p;
            b = last ?? k;
            break;
        }
    }
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

/** The speaker's main naming place in the plan, the same for every edition: among the entries in
 *  this book (word keys starting with prefix), the `named` one with the most clause rows (the
 *  earlier on a tie), else the main `described` one; else the main `named` one in another book
 *  (the Greek names a speaker where they are first named, also in another book); null if none.
 *  namedOnly: never a `described` one (layout.toml [speakers] separate_chapters).
 *  [part, index] (lines.main_naming) */
export function mainNaming(ref, prefix = '', namedOnly = false) {
    for (const [part, here] of [['named', true], ['described', true], ['named', false]]) {
        if (namedOnly && part === 'described') continue;
        let best = null;
        (ref[part] || []).forEach(([keys, n], i) => {
            if (keys.length && keys[0].startsWith(prefix) === here && (best === null || n > ref[part][best][1])) best = i;
        });
        if (best !== null) return [part, best];
    }
    return null;
}

/** speaker_id -> {voice, hits, pointer}: where the edition's text names each speaker, once per book
 *  (lines.speaker_hits). hits: [{part, label, n, chapter, main}] in plan order, part "named" (the
 *  speaker's name) or "described" (the words introducing them), chapter the edition chapter, main:
 *  the hit is at the speaker's main naming place (mainNaming). pointer: that place, {book, verse
 *  (the edition's "c:v"), spine [c, v], keys (source word keys), strong (their Strong's numbers, for
 *  this book's keys)}, or null. refs: the book plan's speakers; toEd(book, cvKey): spine -> edition
 *  cvKey or null; lexemes: lexemeKeys() of the book (optional, for strong). */
export function speakerHits(cfg, refs, al, bt, book = '', toEd = null, lexemes = null) {
    const prefix = BOOKS.includes(book) ? String(BOOKS.indexOf(book) + 1).padStart(2, '0') : '';
    const namedOnly = ((cfg.layout(bt.edition).speakers || {}).separate_chapters || []).includes(book);
    toEd = toEd || ((b, cv) => cv);
    const strongOf = new Map();
    for (const [n, keys] of lexemes || []) for (const k of keys) strongOf.set(k, `${k.length === 11 ? 'G' : 'H'}${n}`);
    const out = new Map();
    for (const [sid, ref] of Object.entries(refs)) {
        const main = mainNaming(ref, prefix, namedOnly);
        const hits = [];
        for (const part of ['named', 'described']) {
            (ref[part] || []).forEach(([keys, n], i) => {
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
                    if (label) hits.push({ part, label, n, chapter: cvC(cv), main: main !== null && main[0] === part && main[1] === i });
                }
            });
        }
        let pointer = null;
        if (main) {
            const keys = ref[main[0]][main[1]][0];
            const bn = /^[0-9]{2}/.test(keys[0]) ? parseInt(keys[0].slice(0, 2), 10) : 0;
            const where = bn > 0 && bn <= BOOKS.length ? BOOKS[bn - 1] : book;
            const spine = cvKey(+keys[0].slice(2, 5), +keys[0].slice(5, 8));
            const ed = toEd(where, spine);
            pointer = {
                book: where, verse: ed === null ? null : `${cvC(ed)}:${ed % 1000}`, spine: [cvC(spine), spine % 1000], keys: [...keys],
                strong: unique(keys.map((k) => strongOf.get(k)).filter(Boolean)),
            };
        }
        out.set(sid, { voice: voiceOf(cfg, sid, ref.voice), hits, pointer });
    }
    return out;
}

/** speaker_id -> {id, label, voice, pointer?} for one edition chapter (lines.speaker_labels). The
 *  label is the commonest of the edition's words naming the speaker in this chapter (named, else
 *  described); where the chapter has none, the words at the speaker's main naming place, and
 *  `pointer` says where that is, so a client with only this chapter can fetch that chapter;
 *  else none (the cast table's name is used). Nothing depends on which other chapters the client
 *  has, except that the pointer's chapter must be among them for its words. chapter null: the
 *  commonest in the book (the cast table). hits: speakerHits(). */
export function speakerLabels(hits, chapter = null) {
    const out = new Map();
    for (const [sid, { voice, hits: hs, pointer }] of hits) {
        const pick = (keep) => {
            for (const part of ['named', 'described']) {
                const c = new Map();       // label -> [places, clause rows]
                for (const h of hs) {
                    if (h.part !== part || !keep(h)) continue;
                    if (!c.has(h.label)) c.set(h.label, [0, 0]);
                    const e = c.get(h.label);
                    e[0] += 1;
                    e[1] += h.n;
                }
                let best = null;
                for (const [k, e] of c) if (best === null || e[0] > c.get(best)[0] || (e[0] === c.get(best)[0] && e[1] > c.get(best)[1])) best = k;
                if (best !== null) return best;
            }
            return null;
        };
        const own = pick((h) => chapter === null || h.chapter === chapter);
        const sp = speaker(sid, own ?? (chapter === null ? null : pick((h) => h.main)), voice);
        if (own === null && chapter !== null && pointer) sp.pointer = pointer;
        out.set(sid, sp);
    }
    return out;
}

/** Lyric lines of an edition chapter (lines.build_lines) */
export function buildLines(cfg, bt, chapter, rows, al, speakers, vmapCv, { minTokens = 3, marks, poetry = 'clauses+halves', textCfg = null, pull = false } = {}) {
    textCfg = textCfg || {};
    const opening = lineStartRule(textCfg);
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
            lines.push(line(cv, v.text, 0, qq, sp, r0 ? r0.seg : null, null, r0));
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
                    if (t === 0 && !cand.has(t) && !fixed.has(t)) continue;   // the verse start: a clause may pull its line back to it
                    let s = t;
                    if (cand.has(t) && !fixed.has(t)) {
                        const lo = next.length ? next[next.length - 1] : -1;
                        while (s - 1 > lo && !own.has(s - 1) && !pyStrip(v.text.slice(v.spans[s - 1][1], v.spans[s][0]))) s--;
                    }
                    next.push(s);
                    moved.set(s, t);
                }
                if (!next.length || next[0] !== 0) {
                    next.unshift(0);
                    moved.set(0, 0);
                }
                starts = next;
            }
            let prevRow = null;
            const first = lines.length;
            for (const [t, piece] of slice(v, starts, opening)) {
                const r = cand.get(moved.has(t) ? moved.get(t) : t) || (owner.get(cv) || new Map()).get(t) || prevRow;
                prevRow = r;
                const [qq, sp] = voice(r);
                lines.push(line(cv, piece, t, qq, sp, r ? r.seg : null, r ? clauseKey(r) : null, r || null));
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
