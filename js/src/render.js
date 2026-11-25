// Suno lyrics: sections with voice tags, and the notes that go with them. Mirrors
// bible_song_builder/render.py. Every lyric line is the edition's own text, verbatim.
import { Stanza } from './lines.js';
import { count, fmtCv, cvC, pyLen, pyStr, pyStrip, wordRuns } from './util.js';

const REFRAIN = Symbol('refrain');

const norm = (s) => wordRuns(s.toLowerCase()).join(' ');

function section(label, stanza, sung, refrain = new Set(), kind = 'start') {
    return { label, stanza, sung, refrain, kind, mood: null };
}

/** Edition lines repeated word for word (chorus source "lines") */
export function repeatedLines(lines, minRepeats, minWords) {
    const c = new Map();
    for (const ln of lines) count(c, norm(ln.text));
    return new Set([...c].filter(([t, n]) => n >= minRepeats && t.split(' ').filter(Boolean).length >= minWords).map(([t]) => t));
}

/** Sections from stanzas (render.sections) */
export function sections(stanzas, setting, sungVerses, chorus = null) {
    chorus = chorus || {};
    const src = chorus.source ?? 'text';
    const all = stanzas.flatMap((s) => s.lines);
    if (src === 'lines') for (const ln of all) ln.refrain = null;
    if (src === 'lines' || src === 'both') {
        const rep = repeatedLines(all, chorus.lines_min_repeats ?? 3, chorus.lines_min_words ?? 3);
        for (const ln of all) if (ln.refrain === null && rep.has(norm(ln.text))) ln.refrain = 'rep:' + norm(ln.text);
    }
    const ids = new Set(all.filter((ln) => ln.refrain).map((ln) => ln.refrain));
    const inline = (chorus.style ?? 'section') === 'inline';

    const occurrences = (lns) => {
        const c = new Map();
        for (const r of new Set(lns.filter((ln) => ln.refrain).map((ln) => ln.refrain))) count(c, r.split('#')[0]);
        return c.size ? Math.max(...c.values()) : 0;
    };

    const out = [];
    let n = 0;
    for (const st of stanzas) {
        const vs = st.verses;
        const sung = vs.filter((v) => sungVerses.has(v)).length * 2 > vs.length;
        const labelSung = setting !== 'prose' || sung;
        if (occurrences(st.lines) >= (inline ? 1 : 2)) {
            // the refrain returns inside the stanza: keep it whole, call and response
            if (setting === 'prose' && sung) out.push(section('Bridge', st, true, ids, st.reason));
            else out.push(section(`Verse ${++n}`, st, labelSung, ids, st.reason));
            continue;
        }
        // cut the stanza around its chorus lines
        const runs = [];
        for (const ln of st.lines) {
            const isCh = ln.refrain !== null;
            if (runs.length && runs[runs.length - 1][0] === isCh) runs[runs.length - 1][1].push(ln);
            else runs.push([isCh, [ln]]);
        }
        // a single line left over in the verse right after a chorus stays with it
        let k = 1;
        while (k < runs.length) {
            const prev = runs[k - 1][1];
            if (runs[k - 1][0] && !runs[k][0] && runs[k][1].length === 1 && runs[k][1][0].cv === prev[prev.length - 1].cv) {
                runs[k - 1][1].push(...runs[k][1]);
                runs.splice(k, 1);
                if (k < runs.length && runs[k][0] === runs[k - 1][0]) {
                    runs[k - 1][1].push(...runs[k][1]);
                    runs.splice(k, 1);
                }
            } else k++;
        }
        runs.forEach(([isCh, lns], k2) => {
            const before = k2 ? runs[k2 - 1][1] : null;
            const kind = k2 === 0 ? st.reason : (lns[0].cv === before[before.length - 1].cv ? 'midverse' : 'chorus');
            if (isCh) out.push(section('Chorus', new Stanza(lns, kind), true, new Set(), kind));
            else if (setting === 'prose' && sung) out.push(section('Bridge', new Stanza(lns, kind), true, new Set(), kind));
            else out.push(section(`Verse ${++n}`, new Stanza(lns, kind), setting !== 'prose', new Set(), kind));
        });
    }
    return out;
}

function range(verses) {
    const a = verses[0], b = verses[verses.length - 1];
    if (a === b) return fmtCv(a);
    return cvC(a) === cvC(b) ? `${fmtCv(a)}-${b % 1000}` : `${fmtCv(a)}-${fmtCv(b)}`;
}

const voiceOfLine = (ln) => (ln.quote === null ? 'narrator' : ln.speaker ? ln.speaker.voice : 'narrator');

/** The tag written for a section, or null (layout.toml [sections]) */
export function sectionTag(label, mode = 'all', numberVerses = true) {
    if (mode === 'none') return null;
    if (label.startsWith('Verse')) {
        if (mode === 'chorus_bridge') return null;
        return numberVerses ? `[${label}]` : '[Verse]';
    }
    return `[${label}]`;
}

/** [the notes, the lyrics] (render.render) */
export function render(bookName, chapter, editionName, setting, secs, credits, profile,
    { maxChars = 5000, extraNotes = null, names = null, layout = null, letterNames = null, styleNote = null } = {}) {
    layout = layout || {};
    const secCfg = layout.sections || {};
    const mode = secCfg.tags ?? 'all', numbered = secCfg.number_verses ?? true;
    const selahTag = (layout.psalms || {}).selah_tag ?? '';
    const tags = profile.tags;
    const body = [];
    const castUsed = new Map();
    let curKey = null, curTag = tags.narrator ?? null, curMood = null;
    for (const s of secs) {
        if (body.length) body.push('');
        const head = sectionTag(s.label, mode, numbered);
        if (head) body.push(head);
        const moodTag = s.mood ? s.mood.tag : null;
        if (moodTag && moodTag !== curMood) body.push(moodTag);   // a section without a mood goes on in the mood before it
        curMood = moodTag || curMood;
        for (const ln of s.stanza.lines) {
            let key, tag;
            if (ln.refrain !== null && s.refrain.has(ln.refrain)) {
                key = REFRAIN;
                tag = tags.refrain ?? '[Choir]';
            } else {
                const v = voiceOfLine(ln);
                key = v === 'narrator' ? null : (ln.speaker && ln.speaker.id ? ln.speaker.id : ln.quote);
                tag = tags[v] ?? '';
                if (v !== 'narrator' && ln.speaker) {
                    const who = (names ? names(ln.speaker) : null) || ln.speaker.label || 'unnamed';
                    if (!castUsed.has(tag)) castUsed.set(tag, []);
                    if (!castUsed.get(tag).includes(who)) castUsed.get(tag).push(who);
                }
            }
            if (key !== curKey && tag && (tag !== curTag || key !== null)) body.push(tag);
            curKey = key;
            curTag = tag;
            body.push(ln.text);
            if (ln.selah && selahTag) body.push(selahTag);
        }
    }
    const lyrics = body.join('\n') + '\n';

    const notes = [`${bookName} ${chapter} · ${editionName} · setting: ${setting}`,
        `Profile: ${profile.name}, ${profile.lead} lead · Suno persona: `
        + (profile.persona || `(not set: profiles.toml [profiles.${profile.name}] persona.${profile.lead})`)];
    if (styleNote) notes.push(styleNote);
    if (castUsed.size) {
        notes.push('Voices: ' + [...castUsed].map(([t, w]) => `${t} ${w.join(', ')}`).join('; ')
            + `; ${pyStr(tags.narrator)} or no tag = the narrator (the persona)`);
    }
    if (mode !== 'all') notes.push(`Section tags: ${mode} (layout.toml); the sections are still listed here`);
    for (const s of secs) {
        const letters = s.stanza.lines.filter((ln) => ln.acrostic).map((ln) => ln.acrostic);
        const let_ = letters.length ? '  · ' + letters.map((x) => pyStrip(`${x} ${(letterNames || {})[x] ?? ''}`)).join(', ') : '';
        const md = s.mood ? `  · ${s.mood.tag} ${s.mood.mood} ${pyStr(s.mood.hebrew)} (${s.mood.family})` + (s.mood.word ? ` “${s.mood.word}”` : '') + `, from ${s.mood.evidence}` + (s.mood.model ? ' (model-read)' : '') : '';
        notes.push(`[${s.label}] ${range(s.stanza.verses)}${let_}${md}`);
    }
    notes.push(...(extraNotes || []));
    notes.push("Shortened or paraphrased: nothing; every line is the edition's text, verbatim.");
    if (pyLen(lyrics) > maxChars) notes.push(`Length: ${pyLen(lyrics)} characters, over ${maxChars}; shorten before use and list the cuts here.`);
    notes.push(...credits);
    return [notes.join('\n') + '\n', lyrics];
}
