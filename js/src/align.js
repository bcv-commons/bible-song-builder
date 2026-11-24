// The join: which edition tokens each Hebrew/Greek word (a MACULA key) aligned to. Mirrors
// bible_song_builder/align.py. Nothing is fetched here: the caller passes a `files` object whose
// async json(dataset, path) and text(dataset, path) give a file of a bcv-commons dataset at its
// pinned revision, or null when there is no such file.
import { cvKey, pySplit, splitOnce } from './util.js';

export class Alignment {
    constructor(kind, layer, file) {
        this.kind = kind;          // "full", "compact" or "none"
        this.layer = layer;
        this.file = file;
        this.chaptersOff = new Set();   // edition chapters whose text differs from the aligned text
        this.links = new Map();         // key -> [edition cvKey, Set of token positions]
    }

    positions(key) {
        const hit = this.links.get(key);
        return hit && hit[1].size ? hit : null;
    }
}

/** "5", "5-7", "5,9", "L3,1,2"; "~" and "!" are no positions */
export function parseSpan(s) {
    if (s.startsWith('L')) s = s.slice(1);
    const out = [];
    for (const part of s.split(',')) {
        if (!part || part === '~' || part === '!') continue;
        if (part.includes('-')) {
            const [a, b] = splitOnce(part, '-');
            if (/^\d+$/.test(a) && /^\d+$/.test(b)) for (let x = +a; x <= +b; x++) out.push(x);
        } else if (/^\d+$/.test(part)) out.push(+part);
    }
    return out;
}

function refToCv(ref) {
    const [, cv] = splitOnce(ref, ' ');
    const [c, v] = cv.split(':');
    return /^\d+$/.test(v) ? cvKey(+c, +v) : null;     // "C:title" has no target words
}

/** spine ref -> edition ref, for every verse whose numbering differs */
export async function verseMap(files, edition) {
    return (await files.json('compact-alignments', `_index/${edition.verse_map}`)).map;
}

export function spineToEdition(vmap, book, cv) {
    const ref = `${book} ${Math.floor(cv / 1000)}:${cv % 1000}`;
    return refToCv(vmap[ref] ?? ref);
}

/** The aligned text's book hash and 5-hex chapter fingerprints (compact-alignments-meta) */
async function publishedFingerprints(files, edition, book) {
    if (!edition.compact_edition) return null;
    const iso = edition.iso;
    const txt = await files.text('compact-alignments-meta', `${iso[0]}/${iso}/${edition.compact_edition}/_fingerprints.txt`);
    if (txt === null) return null;
    for (const line of txt.split(/\r\n|\n|\r/)) {
        const parts = pySplit(line);
        if (parts.length && parts[0] === book) {
            const chapters = new Map();
            let n = 1;
            for (let tok of parts.slice(3)) {
                if (tok.includes(':')) {
                    const [ns, rest] = splitOnce(tok, ':');
                    n = parseInt(ns, 10);
                    tok = rest;
                }
                chapters.set(n, tok);
                n++;
            }
            return [parts[1], chapters];
        }
    }
    return null;
}

/** The alignment of exactly this text (book fingerprint ``fileHash``). If it has no file, the
 *  latest aligned version is used for the chapters whose chapter fingerprint matches, and the
 *  others are marked chaptersOff. chapterFps: Map chapter -> 64-hex. */
export async function loadAlignment(files, edition, book, fileHash, chapterFps = null) {
    let al = await load(files, edition, book, fileHash);
    if (al.kind !== 'none' || !chapterFps) return al;
    const pub = await publishedFingerprints(files, edition, book);
    if (!pub || pub[0] === fileHash) return al;
    al = await load(files, edition, book, pub[0]);
    al.chaptersOff = new Set([...chapterFps].filter(([c, fp]) => pub[1].get(c) !== fp.slice(0, 5)).map(([c]) => c));
    if (al.chaptersOff.size) {
        for (const [k, [cv]] of [...al.links]) if (al.chaptersOff.has(Math.floor(cv / 1000))) al.links.delete(k);
    }
    return al;
}

async function load(files, edition, book, fileHash) {
    const iso = edition.iso;
    const lexemes = await files.json('compact-alignments', `_index/${book}_lexemes.json`);
    const refs = Object.keys(lexemes);
    const keys = await files.json('compact-alignments', `_index/${book}_keys.json`);
    const vmap = await verseMap(files, edition);

    let main = null, fn = null, kind = 'none', layer = null, path = null;
    if (edition.full_layer) {
        layer = edition.full_layer;
        path = `${iso[0]}/${iso}/${layer}/${book}_${fileHash}.json`;
        main = await files.json('full-alignments-manual', path);
        if (main !== null) {
            const meta = await files.json('full-alignments-manual', path.replace('.json', '.meta.json'));
            if (meta === null) main = null;
            else { fn = meta.fn; kind = 'full'; }
        }
    }
    if (main === null && edition.compact_edition) {
        layer = edition.compact_edition;
        path = `${iso[0]}/${iso}/${layer}/${book}_${fileHash}.json`;
        main = await files.json('compact-alignments', path);
        kind = 'compact';
    }
    if (main === null) return new Alignment('none', null, null);

    const fnKeys = fn ? await files.json('compact-alignments', `_index/${book}_fn_keys.json`) : {};
    const al = new Alignment(kind, layer, path);
    const add = (keyList, ordinal, target, pos) => {
        if (ordinal >= keyList.length) return;
        for (const k of keyList[ordinal].split('+')) {
            if (!k) continue;
            let hit = al.links.get(k);
            if (!hit) { hit = [target, new Set()]; al.links.set(k, hit); }
            for (const p of pos) hit[1].add(p);
        }
    };
    refs.forEach((ref, i) => {
        const target = refToCv(vmap[ref] ?? ref);
        if (target === null) return;
        const ck = keys[ref] || [];
        const fk = fn ? fnKeys[ref] || [] : [];
        const strings = [[main[i], ck], ...(fn ? [[fn[i], fk]] : [])];
        for (const [s, klist] of strings) {
            for (const entry of pySplit(s)) {
                const head = entry[0];
                if ('!ue'.includes(head)) continue;            // no target word of its own
                if (head === '+') {                            // supplied words, owned by a token
                    for (const item of entry.slice(1).split(',')) {
                        if (!item.includes('>')) continue;
                        const [pos, owner] = splitOnce(item, '>');
                        if (owner.startsWith('f')) add(fk, parseInt(owner.slice(1), 10), target, [parseInt(pos, 10)]);
                        else add(ck, parseInt(owner, 10), target, [parseInt(pos, 10)]);
                    }
                    continue;
                }
                if (!entry.includes(':')) continue;
                const [o, span] = splitOnce(entry, ':');
                if (/^\d+$/.test(o)) add(klist, parseInt(o, 10), target, parseSpan(span));
            }
        }
    });
    return al;
}
