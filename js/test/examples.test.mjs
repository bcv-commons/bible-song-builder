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
