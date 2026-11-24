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
    assert.deepEqual(['md.samach', 'md.yare', 'md.sane'].map((f) => ctx.words.get(f)), ['rejoice', 'fear', 'hate']);
    // an alignment that covers the psalm heading (the BSB's does not): למנצח on the first two words of 22:1
    al.links.set('190220010011', [22001, new Set([0])]);
    al.links.set('190220010012', [22001, new Set([1])]);
    const res = projectChapter(prepareBook({ cfg, edition, book: 'PSA', bt, al, bookPlan: bp, vmap }), 22,
        chapterPlan(await chapterPlanDocs(ROOT, 'PSA', 22)));
    assert.ok(res.notes.includes('Heading terms (not sung): God (למנצח);'), res.notes);
});
