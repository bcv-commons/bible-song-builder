// The JS projection gives examples/ byte for byte (the same chapters the Python builds).
// Needs plan/ (make plans), dist/config.json (make client) and cache/ (make setup).
import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { buildBook, loadConfig } from '../node/build.js';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const EXAMPLES = [['RUT', 1], ['PSA', 22], ['PSA', 23], ['PSA', 136], ['EXO', 15], ['EXO', 39], ['LUK', 1]];

test('examples/ byte for byte', async () => {
    const cfg = await loadConfig(ROOT);
    const got = {};
    for (const [book, c] of EXAMPLES) {
        for (const [name, text] of Object.entries(await buildBook(ROOT, cfg, 'BSB', book, [c]))) got[`${book}/${name}`] = text;
    }
    const want = {};
    for (const book of await readdir(join(ROOT, 'examples'))) {
        for (const name of await readdir(join(ROOT, 'examples', book))) want[`${book}/${name}`] = await readFile(join(ROOT, 'examples', book, name), 'utf8');
    }
    assert.deepEqual(Object.keys(got).sort(), Object.keys(want).sort());
    for (const k of Object.keys(want).sort()) assert.equal(got[k], want[k], k);
});

test('spine chapters two away (align.spine_chapters)', async () => {
    const { spineChapters } = await import('../src/index.js');
    const vmap = { 'PSA 115:1': 'PSA 113:9', 'PSA 114:1': 'PSA 113:1', 'GEN 9:1': 'PSA 113:2' };
    assert.deepEqual(spineChapters(vmap, 'PSA', 113), [112, 113, 114, 115]);
    assert.deepEqual(spineChapters({}, 'RUT', 1), [1, 2]);
});

test('version matches the Python package', async () => {
    const { VERSION } = await import('../src/index.js');
    const init = await readFile(join(ROOT, 'bible_song_builder', '__init__.py'), 'utf8');
    assert.ok(init.includes(`"${VERSION}"`), `bible_song_builder/__init__.py has another version than ${VERSION}`);
});

test('mood family words and heading words in the edition', async () => {
    const { Config, chapterPlan, lexemeKeys, loadAlignment, loadBookText, prepareBook, projectChapter, verseMap } = await import('../src/index.js');
    const { bookPlan, cacheFiles, chapterPlanDocs, readJson, releaseUsj } = await import('../node/files.js');
    const cfg = new Config(await readJson(join(ROOT, 'dist', 'config.json')));
    const edition = { name: 'BSB', ...cfg.pins.editions.BSB };
    const files = cacheFiles(ROOT, cfg.pins);
    const bt = await loadBookText(cfg, edition, 'PSA', await releaseUsj(ROOT, cfg.pins, edition.text, 'PSA'));
    const al = await loadAlignment(files, edition, 'PSA', bt.fileHash, bt.chapterFingerprints);
    const bp = await bookPlan(ROOT, 'PSA');
    const vmap = await verseMap(files, edition);
    const ctx = prepareBook({ cfg, edition, book: 'PSA', bt, al, bookPlan: bp, vmap, lexemes: await lexemeKeys(files, 'PSA') });
    assert.deepEqual(['simchah', 'tsarah', 'sinah'].map((m) => ctx.words.get(m)), ['joy', 'trouble', 'hatred']);
    // an alignment that covers the psalm heading (the BSB's does not): למנצח on the first two words of 22:1
    al.links.set('190220010011', [22001, new Set([0])]);
    al.links.set('190220010012', [22001, new Set([1])]);
    const res = projectChapter(prepareBook({ cfg, edition, book: 'PSA', bt, al, bookPlan: bp, vmap }), 22,
        chapterPlan(await chapterPlanDocs(ROOT, 'PSA', 22)));
    assert.ok(res.notes.includes('Heading terms (not sung): God (למנצח);'), res.notes);
});

test('a compact alignment: lines start before the unlinked words of a clause', async () => {
    const { buildBook, loadConfig } = await import('../node/build.js');
    const cfg = await loadConfig(ROOT);
    cfg.pins.editions.BSB = { ...cfg.pins.editions.BSB, full_layer: null };
    const out = await buildBook(ROOT, cfg, 'BSB', 'RUT', [1]);
    assert.ok(out['RUT_001.lyrics.txt'].includes('\nwhen the judges ruled,\nthere was a famine in the land.\n'));
    assert.ok(out['RUT_001.json'].includes('"kind": "compact"'));
});

test('bookText: one chapter as plain data, with the chapter its speaker pointer names, gives the whole book\'s song', async () => {
    const { bookText, chapterFiles, chapterPlan, lexemeKeys, loadAlignment, loadBookText, prepareBook, projectChapter, verseMap } = await import('../src/index.js');
    const { bookPlan, cacheFiles, chapterPlanDocs, releaseUsj } = await import('../node/files.js');
    const cfg = await loadConfig(ROOT);
    const edition = { name: 'BSB', ...cfg.pins.editions.BSB, full_layer: null };   // compact: matched per chapter
    const files = cacheFiles(ROOT, cfg.pins);
    const vmap = await verseMap(files, edition);
    const whole = await loadBookText(cfg, edition, 'RUT', await releaseUsj(ROOT, cfg.pins, edition.text, 'RUT'));
    const k = (cv) => `${Math.floor(cv / 1000)}:${cv % 1000}`;
    const part = async (chs) => {
        const inChs = (cv) => chs.includes(Math.floor(cv / 1000));
        return bookText(edition, 'RUT', {
            verses: Object.fromEntries(chs.flatMap((c) => whole.chapterVerses(c)).map((v) => [`${v.chapter}:${v.verse}`, v.text])),
            paragraphStarts: [...whole.paragraphStarts].filter(inChs).map(k),
            headingBefore: [...whole.headingBefore].filter(inChs).map(k),
            poetryVerses: [...whole.poetryVerses].filter(inChs).map(k),
            name: whole.name,
        });
    };
    const song = async (bt) => {
        const al = await loadAlignment(files, edition, 'RUT', bt.fileHash, bt.chapterFingerprints);
        const ctx = prepareBook({ cfg, edition, book: 'RUT', bt, al, bookPlan: await bookPlan(ROOT, 'RUT'), vmap, lexemes: await lexemeKeys(files, 'RUT') });
        const res = projectChapter(ctx, 1, chapterPlan(await chapterPlanDocs(ROOT, 'RUT', 1, vmap)));
        return [chapterFiles(ctx, 1, res), res];
    };
    const one = await part([1]);
    assert.equal(one.chapterFingerprints.get(1), whole.chapterFingerprints.get(1));
    const [a] = await song(whole);
    const [b, res] = await song(one);
    assert.equal(b['RUT_001.lyrics.txt'], a['RUT_001.lyrics.txt']);
    // the women of 1:19 are named only in 4:14: the pointer says so
    const women = res.data.sections.flatMap((s) => s.lines).map((ln) => ln.speaker).find((sp) => sp && sp.pointer);
    assert.deepEqual([women.pointer.book, women.pointer.verse, women.pointer.strong], ['RUT', '4:14', ['H802']]);
    assert.ok(b['RUT_001.notes.txt'].includes("Named in another chapter: the women at RUT 4:14 (H802), not loaded: the cast table's name"));
    const [c] = await song(await part([1, 4]));
    assert.equal(c['RUT_001.notes.txt'], a['RUT_001.notes.txt']);
    assert.equal(c['RUT_001.json'].replace(/"text_fingerprint": "[0-9a-f]+"/, ''), a['RUT_001.json'].replace(/"text_fingerprint": "[0-9a-f]+"/, ''));
});
