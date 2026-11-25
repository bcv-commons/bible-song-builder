// Half 2 for a book and its chapters: a song plan laid onto one edition's text through its
// alignment. Mirrors bible_song_builder/__main__.py (build_chapter, credits, write_book_files) and
// plan.ChapterPlan. Every input is passed in; nothing is fetched here.
import { castName, profileFor } from './config.js';
import { spineToEdition } from './align.js';
import { buildLines, countUnits, phrase, speakerHits, speakerLabels, stanzas } from './lines.js';
import { applyOverrides, chapterStyle, editionMoods, familyWords, sectionMoods, sourceCredits, spanConfig, spanSectionMoods, withReadings } from './moods.js';
import { render, sections } from './render.js';
import { chapterMarks, settingVerses } from './textforms.js';
import { cvC, cvKey, fmtCv, pyLen, removePrefix, sortedNums } from './util.js';

export const VERSION = '0.4.1';
const PLAN_SCHEMA_MAJOR = '1';

/** What half 2 reads for edition chapter c: the plans of the spine chapters spineChapters names
 *  (those that exist), joined (plan.ChapterPlan). */
export function chapterPlan(docs) {
    for (const d of docs) {
        if (String(d.schema).split('.')[0] !== PLAN_SCHEMA_MAJOR) throw new Error(`plan schema ${d.schema}, this code reads ${PLAN_SCHEMA_MAJOR}.x`);
    }
    const union = (part, key) => {
        const seen = new Map();
        for (const d of docs) for (const x of d[part] || []) if (!seen.has(x[key])) seen.set(x[key], x);
        return sortedNums(seen.keys()).map((k) => seen.get(k));
    };
    const facts = union('facts', 'n');
    return {
        rows: docs.flatMap((d) => d.rows),
        signals: Object.assign({}, ...docs.map((d) => d.signals)),
        facts,
        moodFacts: union('mood_facts', 'n'),
        modelMoods: union('model_moods', 'm'),
        moodSpans: union('mood_spans', 's'),        // passage-mood-spans-model (schema 1.1)
        labels: Object.fromEntries(facts.filter((f) => 'label' in f).map((f) => [f.value, f.label])),
    };
}

/** Options not given, from layout.toml (apply_layout_defaults) */
export function withDefaults(cfg, edition, args = {}) {
    const lay = cfg.layout(edition);
    const out = { style: null, profile: null, lead: null, ...args };
    for (const [opt, sec, key, dflt] of [['max_lines', 'stanzas', 'max_lines', 12], ['min_words', 'lines', 'min_words', 3],
        ['max_chars', 'length', 'max_chars', 5000]]) {
        if (out[opt] === undefined || out[opt] === null) out[opt] = (lay[sec] || {})[key] ?? dflt;
    }
    return out;
}

/** The book-level work, once per book: speakers, profile, chapter moods.
 *  edition: {name, iso, licence, full_layer, compact_edition, verse_map}; bt: loadBookText();
 *  al: loadAlignment(); bookPlan: plan/<BOOK>/<BOOK>.json; vmap: verseMap();
 *  lexemes: lexemeKeys(), for the edition's words of the section moods (optional). */
export function prepareBook({ cfg, edition, book, bt, al, bookPlan, vmap, lexemes = null, args = {} }) {
    if (String(bookPlan.schema).split('.')[0] !== PLAN_SCHEMA_MAJOR) throw new Error(`plan schema ${bookPlan.schema}, this code reads ${PLAN_SCHEMA_MAJOR}.x`);
    args = withDefaults(cfg, edition, args);
    const profile = profileFor(cfg, edition, book, args.profile, args.lead);
    const toEd = (cv) => spineToEdition(vmap, book, cv);
    return {
        cfg, edition, book, bt, al, bookPlan, vmap, args, profile, toEd,
        speakers: speakerHits(cfg, bookPlan.speakers, al, bt, book, (b, cv) => spineToEdition(vmap, b, cv), lexemes),
        moods: applyOverrides(cfg, book, withReadings(cfg, editionMoods(bookPlan, toEd), bookPlan.readings || [], toEd), profile),
        words: lexemes ? familyWords(cfg, lexemes, al, bt, bookPlan.testament) : new Map(),
    };
}

/** The edition chapters of the book */
export const chapters = (ctx) => sortedNums(new Set([...ctx.bt.verses.keys()].map(cvC)));

function credits(ctx) {
    const { cfg, edition, al, bookPlan: bp } = ctx;
    const hf = cfg.pins.huggingface;
    const sp = bp.pins;
    const ds = bp.lines_dataset;
    const out = [
        `Text: ${edition.name}, ${edition.licence}.`,
        `Structure: bcv-commons/${ds} ${sp[ds].tag}, passage-facts ${sp['passage-facts'].tag}, `
        + `clause-connectives ${sp['clause-connectives'].tag} and clause-columns ${sp['clause-columns'].tag}, `
        + 'CC BY-SA 4.0 (bcv-commons; MACULA, Clear Bible / Biblica, CC BY 4.0; '
        + 'MAM, unfoldingWord ULT, UBS dictionaries, CC BY-SA 4.0).',
    ];
    if (al.kind === 'full') {
        out.push(`Alignment: bcv-commons/full-alignments-manual ${hf['full-alignments-manual'].tag}, `
            + `layer ${al.layer} (BSB translation tables, CC0).`);
    } else if (al.kind === 'compact') {
        out.push(`Alignment: bcv-commons/compact-alignments @${hf['compact-alignments'].revision.slice(0, 10)}, ${al.layer}, CC0.`);
    } else {
        out.push('Alignment: none for this text; lines break at verse ends only.');
    }
    return out;
}

function chapterCredits(ctx, chapter, mood, secMoods) {
    let out = credits(ctx);
    if (ctx.al.chaptersOff.has(chapter)) {
        out = out.map((c) => (!c.startsWith('Alignment:') ? c
            : "Alignment: none for this chapter (the edition's text differs from the aligned text); lines break at verse ends only."));
    }
    return [...out, ...sourceCredits(mood, secMoods, ctx.bookPlan.pins, ctx.bookPlan.sources).map((c) => `Mood: ${c}`)];
}

const pad3 = (n) => String(n).padStart(3, '0');

/** layout.toml [lines] pull_unaligned: "compact" (content-word alignments only), "always", "never" */
function pullUnaligned(layout, al) {
    const mode = (layout.lines || {}).pull_unaligned ?? 'compact';
    return mode === 'always' || (mode === 'compact' && al.kind === 'compact');
}

/** One edition chapter: {notes, lyrics, style, own_style, data}. plan: chapterPlan(...) */
export function projectChapter(ctx, chapter, plan) {
    const { cfg, edition, book, bt, al, bookPlan: bp, profile, toEd, args } = ctx;
    const mood = ctx.moods.get(chapter) || null;
    const layout = cfg.layout(edition);
    const marks = chapterMarks(plan.facts, plan.rows, al, chapter, layout);
    const lyricLines = buildLines(cfg, bt, chapter, plan.rows, al, speakerLabels(ctx.speakers, chapter), toEd, {
        minTokens: args.min_words, marks, poetry: (layout.lines || {}).poetry ?? 'clauses+halves', textCfg: layout.text,
        pull: pullUnaligned(layout, al),
    });
    const sts = stanzas(lyricLines, bt, args.max_lines, plan.signals, layout.stanzas || {}, bp.testament === 'nt');
    const elsewhere = new Map();
    for (const ln of lyricLines) if (ln.speaker && ln.speaker.pointer) elsewhere.set(ln.speaker.id, ln.speaker);

    const spine = sortedNums(new Set(plan.rows.map((r) => cvKey(r.chapter, r.verse))));
    const sv = settingVerses(plan.facts, spine, layout.setting);
    const inChapter = (vs) => new Set([...vs].map(toEd).filter((e) => e !== null && cvC(e) === chapter));
    const song = inChapter(sv.song), poetic = inChapter(sv.poetic);
    const sungOrPoetic = new Set([...song, ...poetic]);
    const n = Math.max(bt.chapterVerses(chapter).length, 1);
    const share = (layout.setting || {}).share ?? 0.5;
    const setting = song.size >= share * n ? 'song' : sungOrPoetic.size >= share * n ? 'poetry' : 'prose';
    const secs = sections(sts, setting, sungOrPoetic, layout.chorus);
    let secMoods = null;
    const countMode = (layout.text || {}).count || 'words';
    for (const src of spanConfig(cfg).sections) {
        if (src === 'spans') {
            secMoods = spanSectionMoods(cfg, book, secs.map((s) => s.stanza.lines.map((ln) => [ln.row, countUnits(ln.text, countMode)])),
                plan.rows, plan.moodSpans, profile, ctx.words);
        } else if (src === 'words') {
            secMoods = sectionMoods(cfg, book, secs.map((s) => s.stanza.verses), plan.moodFacts, plan.modelMoods, toEd, profile, ctx.words);
        }
        if (secMoods !== null && secMoods.some(Boolean)) break;
    }
    secMoods = secMoods || secs.map(() => null);
    secs.forEach((s, i) => { s.mood = secMoods[i]; });

    const titles = sortedNums(bt.titles.keys()).filter((k) => cvC(k) === chapter);
    const notes = titles.map((k) => `Superscription before ${fmtCv(k)} (not sung): ${bt.titles.get(k)}`);
    if ((layout.psalms || {}).heading_terms ?? true) {
        if (marks.headingTerms.length) {
            const term = (code) => {
                const gloss = removePrefix(plan.labels[code] ?? code, 'heading: ').split(': a term of the text')[0];
                const at = marks.headingWords.get(code);
                const own = at ? phrase(cfg, bt, at[0], at[1], 12) : null;
                const i = gloss.indexOf(' (');
                return own && i >= 0 ? `${own} (${gloss.slice(i + 2)}` : gloss;
            };
            notes.push('Heading terms (not sung): ' + marks.headingTerms.map(term).join('; '));
        }
        if (marks.selah.size) notes.push('Selah at ' + sortedNums(marks.selah.keys()).map(fmtCv).join(', '));
    }
    if (elsewhere.size) {
        notes.push('Named in another chapter: ' + [...elsewhere.values()].map((sp) => `${sp.label || castName(cfg, sp.id) || sp.id} at `
            + `${sp.pointer.book} ${sp.pointer.verse ?? sp.pointer.spine.join(':')}${sp.pointer.strong.length ? ` (${sp.pointer.strong.join(' ')})` : ''}`
            + (sp.label ? '' : ", not loaded: the cast table's name")).join('; '));
    }
    const letterNames = cfg.language(edition.iso).hebrew_letters || {};
    if (marks.letters.length && !marks.acrosticRuns.size) {
        notes.push('Acrostic (each unit starts with the next letter): ' + marks.letters.map(([[cv], x]) => `${fmtCv(cv)} ${x}`).join(', '));
    }

    const [style, added] = args.style ? [args.style, null] : chapterStyle(cfg, profile, mood);
    const stem = `${book}_${pad3(chapter)}`;
    let styleNote = added && mood
        ? `Style: this chapter's own (${stem}.style.txt): ${mood.mood || 'instruments'} (+ "${added}"), from ${mood.basis}: ${mood.evidence}`
        : `Style: the book's (${book}.style.txt, profile ${profile.name})`
          + (mood ? `; the source names ${mood.evidence}, which sets no style in profile ${profile.name}` : '');
    styleNote += `. To change: config/books/${book}.toml, [chapters.${chapter}] (mood or style)`;
    if (args.style) styleNote = 'Style: given on the command line (--style)';

    const [notesText, lyrics] = render(bt.name, chapter, edition.name, setting, secs,
        chapterCredits(ctx, chapter, mood, secMoods), profile, {
            maxChars: args.max_chars, names: (sp) => sp.label || castName(cfg, sp.id), extraNotes: notes, layout,
            letterNames, styleNote,
        });
    const ownStyle = Boolean(added) || Boolean(args.style);
    const data = {
        book, chapter, edition: edition.name, setting,
        profile: { name: profile.name, lead: profile.lead, persona: profile.persona, style: profile.style, tags: profile.tags },
        style, own_style: ownStyle,
        mood: mood ? { mood: mood.mood, basis: mood.basis, evidence: mood.evidence, instruments: [...mood.instruments] } : null,
        text_fingerprint: bt.fingerprint,
        superscription: titles.length ? bt.titles.get(titles[0]) : null,
        alignment: { kind: al.kind, layer: al.layer, file: al.file },
        pins: cfg.pins.huggingface, 'bible-song-builder': VERSION,
        sections: secs.map((s) => ({
            label: s.label, sung: s.sung,
            mood: s.mood ? { mood: s.mood.mood, hebrew: s.mood.hebrew, family: s.mood.family, head: s.mood.head, tag: s.mood.tag, word: s.mood.word, evidence: s.mood.evidence, model: s.mood.model } : null,
            verses: s.stanza.verses.map(fmtCv),
            lines: s.stanza.lines.map((ln) => ({
                verse: fmtCv(ln.cv), token: ln.first_token, text: ln.text, quote: ln.quote,
                speaker: ln.speaker ? { id: ln.speaker.id, label: ln.speaker.label, voice: ln.speaker.voice, ...(ln.speaker.pointer ? { pointer: ln.speaker.pointer } : {}) } : null,
                segment: ln.row_seg, refrain: ln.refrain, acrostic: ln.acrostic, selah: ln.selah,
            })),
            starts: s.kind,
        })),
    };
    return { notes: notesText, lyrics, style, own_style: ownStyle, data, chars: pyLen(lyrics) };
}

/** The files of one chapter, as the CLI writes them: {name: text} */
export function chapterFiles(ctx, chapter, res) {
    const stem = `${ctx.book}_${pad3(chapter)}`;
    return {
        ...(res.own_style ? { [`${stem}.style.txt`]: res.style + '\n' } : {}),
        [`${stem}.lyrics.txt`]: res.lyrics,
        [`${stem}.notes.txt`]: res.notes,
        [`${stem}.json`]: JSON.stringify(res.data, null, 1),
    };
}

/** <BOOK>.style.txt (the book's style line) and <BOOK>.notes.txt (which chapters have their own) */
export function bookFiles(ctx) {
    const { cfg, book, profile, args } = ctx;
    const style = args.style || profile.style;
    const own = [];
    for (const c of sortedNums(ctx.moods.keys())) {
        const m = ctx.moods.get(c);
        const [, added] = chapterStyle(cfg, profile, m);
        if (added && !args.style) own.push(`${book} ${c}: ${m.mood || 'instruments'} (+ "${added}"), from ${m.basis}: ${m.evidence}`);
    }
    const lines = [`${book} · profile ${profile.name}, ${profile.lead} lead · settings: config/books/`
        + (cfg.hasOwnBook(book) ? `${book}.toml` : '_default.toml'),
    `Style for every chapter: ${book}.style.txt — except the chapters below, which have their own`,
    '<chapter>.style.txt (the same style with a mood the Hebrew/Greek gives the chapter).', '',
    ...(own.length ? own : ['(no chapter of this book has its own style)'])];
    return { [`${book}.style.txt`]: style + '\n', [`${book}.notes.txt`]: lines.join('\n') + '\n' };
}
