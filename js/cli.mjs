#!/usr/bin/env node
// node js/cli.mjs BOOK CHAPTER... [--out DIR] [--edition BSB]   ('all' for every chapter)
// Writes <out>/<BOOK>/ as the Python CLI does with --bare. Reads plan/, dist/config.json and cache/.
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildBook, loadConfig } from './node/build.js';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const argv = process.argv.slice(2);
const opt = (name, dflt) => {
    const i = argv.indexOf(name);
    if (i < 0) return dflt;
    const v = argv[i + 1];
    argv.splice(i, 2);
    return v;
};
const out = opt('--out', join(ROOT, 'output'));
const edition = opt('--edition', 'BSB');
const [book, ...chs] = argv;
if (!book || !chs.length) {
    console.error('usage: node js/cli.mjs BOOK CHAPTER... [--out DIR] [--edition BSB]');
    process.exit(2);
}
const cfg = await loadConfig(ROOT);
const files = await buildBook(ROOT, cfg, edition, book.toUpperCase(), chs[0] === 'all' ? 'all' : chs.map(Number));
const dir = join(out, book.toUpperCase());
await mkdir(dir, { recursive: true });
for (const [name, text] of Object.entries(files)) await writeFile(join(dir, name), text, 'utf8');
console.log(`${dir}: ${Object.keys(files).length} files`);
