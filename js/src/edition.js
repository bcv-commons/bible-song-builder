// The lyric-language text: one edition's book, verse by verse, read the shared bcv-commons way
// (vendored tools/verse-text). Mirrors bible_song_builder/edition.py. The caller passes the
// book's USJ; nothing is fetched here.
import { extractUsj } from '../../vendor/verse_text/js/extract_usj.js';
import { firstNumber } from '../../vendor/verse_text/js/rule.js';
import { fileHash, fingerprints } from '../../vendor/verse_text/js/text_fingerprint.mjs';
import { stripMarks, tokenize } from '../../vendor/verse_text/js/tokenize.js';
import { ConfigError, cvC, cvKey, isObj, isPySpace, pyRstrip, pySplit, pyStrip } from './util.js';

const PARAGRAPH_MARKERS = new Set(['p', 'm', 'pmo', 'pm', 'pi', 'pi1', 'pi2', 'nb', 'po', 'pr', 'mi']);
const POETRY_PREFIX = 'q';
export const FIXES = ['titles-in-d', 'note-spaces', 'span-spaces'];
const LETTER_OR_MARK = /^[\p{L}\p{M}]$/u;
const ALNUM = /^[\p{L}\p{N}]$/u;

export class BookText {
    constructor(edition, book, verses, fingerprint, chapterFingerprints) {
        this.edition = edition;            // the edition descriptor
        this.book = book;
        this.verses = verses;              // Map cvKey -> {chapter, verse, text, tokens, spans}
        this.fingerprint = fingerprint;
        this.chapterFingerprints = chapterFingerprints;   // Map chapter -> 64-hex
        this.paragraphStarts = new Set();  // a prose paragraph opens at this verse
        this.headingBefore = new Set();    // a section heading stands before this verse
        this.poetryVerses = new Set();     // the edition sets the verse in poetic lines
        this.name = '';                    // the book's short name (\toc2)
        this.titles = new Map();           // cvKey -> superscription before this verse
    }

    get fileHash() {
        return fileHash(this.fingerprint);
    }

    chapterVerses(chapter) {
        return [...this.verses.keys()].filter((k) => cvC(k) === chapter).sort((a, b) => a - b).map((k) => this.verses.get(k));
    }
}

/** Offsets of the tokens tokenize(text) gives (UTF-16 offsets into text), or null where the
 *  per-character reading cannot reproduce them. */
export function tokenSpans(text) {
    const spans = [];
    let start = null;
    let i = 0;
    for (const ch of text) {
        const s = stripMarks(ch);
        const isWord = s !== '' && [...s].every((c) => LETTER_OR_MARK.test(c));
        if (isWord && start === null) start = i;
        else if (!isWord && start !== null && s !== '') {
            spans.push([start, i]);
            start = null;
        }
        i += ch.length;
    }
    if (start !== null) spans.push([start, text.length]);
    const got = spans.map(([a, b]) => stripMarks(text.slice(a, b)));
    const want = tokenize(text);
    if (got.length !== want.length || got.some((t, k) => t !== want[k])) return null;
    return spans;
}

const is = (n, kind) => isObj(n) && n.type === kind;

function usjText(n) {
    if (typeof n === 'string') return n;
    return (n.content || []).map(usjText).join('');
}

/** Paragraph starts, headings and poetic verses from the USJ's paragraph markers */
function walkLayout(usj, bt) {
    let chapter = 0;
    let lastVerse = null;
    let pendingHeading = false;
    for (const node of usj.content) {
        if (node.type === 'chapter') {
            chapter = parseInt(node.number, 10);
            continue;
        }
        if (node.type !== 'para') continue;
        const marker = node.marker || '';
        const content = node.content || [];
        if (marker.startsWith('s') || ['ms', 'mr', 'd'].includes(marker)) {
            pendingHeading = true;
            continue;
        }
        const opens = content.length > 0 && is(content[0], 'verse');
        const nums = content.filter((x) => is(x, 'verse')).map((x) => parseInt(firstNumber(x.number), 10));
        if (opens) {
            const here = cvKey(chapter, nums[0]);
            if (PARAGRAPH_MARKERS.has(marker)) bt.paragraphStarts.add(here);
            if (pendingHeading) bt.headingBefore.add(here);
        }
        if (marker.startsWith(POETRY_PREFIX)) {
            for (const v of [...(lastVerse !== null && !opens ? [lastVerse] : []), ...nums.map((n) => cvKey(chapter, n))]) {
                bt.poetryVerses.add(v);
            }
        }
        if (nums.length) {
            lastVerse = cvKey(chapter, nums[nums.length - 1]);
            pendingHeading = false;
        }
    }
}

/** A psalm title is a \d paragraph that holds the verse-1 marker. The title's text stays in the d
 *  paragraph (not sung) and the verse marker moves to the next paragraph with content. */
export function liftTitles(usj) {
    const titles = new Map();
    const cont = usj.content;
    let chapter = 0;
    cont.forEach((p, i) => {
        if (is(p, 'chapter')) chapter = parseInt(p.number, 10);
        if (!(is(p, 'para') && p.marker === 'd')) return;
        const vs = (p.content || []).filter((x) => is(x, 'verse'));
        if (!vs.length) return;
        const title = pySplit(p.content.filter((x) => !is(x, 'verse') && !is(x, 'note'))
            .map((x) => (isObj(x) ? usjText(x) : x)).join(' '));
        p.content = p.content.filter((x) => !is(x, 'verse'));
        for (const q of cont.slice(i + 1)) {
            if (is(q, 'para') && q.content && q.content.length) {
                q.content = [...vs, ' ', ...q.content];
                break;
            }
        }
        titles.set(cvKey(chapter, parseInt(firstNumber(vs[0].number), 10)), title.join(' '));
    });
    return titles;
}

/** Put back the space a USJ export drops between a footnote (or char span) and a following char span */
export function restoreNoteSpaces(n) {
    if (!isObj(n) || !Array.isArray(n.content) || n.type === 'note') return 0;
    const out = [];
    let k = 0;
    for (const x of n.content) {
        const last = out[out.length - 1];
        if (out.length && is(x, 'char') && isObj(last) && (last.type === 'note' || last.type === 'char')) {
            out.push(' ');
            k++;
        }
        out.push(x);
    }
    n.content = out;
    return out.reduce((s, x) => s + restoreNoteSpaces(x), k);
}

/** Drop the space inside a char span when the text after it starts with punctuation */
export function trimSpanSpaces(n) {
    if (!isObj(n) || !Array.isArray(n.content)) return 0;
    let k = 0;
    const c = n.content;
    c.forEach((x, i) => {
        const nxt = i + 1 < c.length ? c[i + 1] : null;
        const first = typeof nxt === 'string' ? [...nxt][0] : undefined;
        if (is(x, 'char') && first !== undefined && !ALNUM.test(first) && !isPySpace(first)
            && x.content && x.content.length && typeof x.content[x.content.length - 1] === 'string'
            && x.content[x.content.length - 1].endsWith(' ')) {
            x.content[x.content.length - 1] = pyRstrip(x.content[x.content.length - 1]);
            k++;
        }
    });
    return c.reduce((s, x) => s + trimSpanSpaces(x), k);
}

function bookName(usj, book) {
    const found = {};
    for (const p of usj.content) {
        if (is(p, 'para') && (p.marker === 'toc2' || p.marker === 'h')) found[p.marker] = pyStrip(usjText(p));
    }
    return found.toc2 || found.h || book;
}

/** The edition's text of a book from its USJ, with the repairs editions.toml lists for it.
 *  edition: {name, iso, ...}; usj: the parsed USJ (not changed). */
export async function loadBookText(cfg, edition, book, usj) {
    const ecfg = cfg.edition(edition.name);
    const fixes = ecfg.fixes || [];
    const unknown = fixes.filter((f) => !FIXES.includes(f));
    if (unknown.length) {
        throw new ConfigError(`config/editions.toml [${edition.name}]: unknown fix(es) ${unknown.join(', ')}; known: ${FIXES.join(', ')}`);
    }
    usj = structuredClone(usj);
    let titles = new Map();
    if (fixes.includes('note-spaces')) restoreNoteSpaces(usj);
    if (fixes.includes('span-spaces')) trimSpanSpaces(usj);
    if (fixes.includes('titles-in-d') && (ecfg.title_books || []).includes(book)) titles = liftTitles(usj);
    const verses = new Map();
    for (const [ch, vs] of Object.entries(extractUsj(usj))) {
        for (const v of vs) {
            const key = cvKey(parseInt(ch, 10), parseInt(v.verse, 10));
            verses.set(key, { chapter: cvC(key), verse: key % 1000, text: v.text, tokens: tokenize(v.text), spans: tokenSpans(v.text) });
        }
    }
    const fp = await fingerprints(new Map([...verses].map(([k, v]) => [`${cvC(k)}:${k % 1000}`, v.text])));
    const bt = new BookText(edition, book, verses, fp.book,
        new Map(Object.entries(fp.chapters).map(([c, h]) => [parseInt(c, 10), h])));
    bt.name = bookName(usj, book);
    bt.titles = titles;
    walkLayout(usj, bt);
    return bt;
}
