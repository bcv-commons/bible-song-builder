#!/usr/bin/env node
// A sample client: one chapter's lyrics, Style and notes from the library.
//
//   node js/sample/client.mjs PSA 23
//
// A client gathers five inputs and hands them to the library; the library fetches nothing. This
// sample reads them from this repository's folders (the BSB, which Python downloaded into cache/).
// A web app fetches the same things over HTTP instead, just in time; the comments say from where.
import { readFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Config, chapterPlan, lexemeKeys, loadAlignment, loadBookText, prepareBook, projectChapter, verseMap } from '../src/index.js';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const [book = 'PSA', chapter = '23'] = process.argv.slice(2);
const c = Number(chapter);
const json = async (...p) => JSON.parse(await readFile(join(ROOT, ...p), 'utf8'));
const orNull = (p) => p.catch((e) => { if (e.code === 'ENOENT') return null; throw e; });

// 1. The config: dist/config.json (a release of this repo; the app serves it with the site).
const cfg = new Config(await json('dist', 'config.json'));

// 2. The edition: name, language, licence, and which alignment layer and verse map it uses.
//    A web app reads these from the bibles catalog (edition-struct.json); here, pins.json.
const edition = { name: 'BSB', ...cfg.pins.editions.BSB };

// 3. The edition's text of the book, as USJ. A web app fetches it through the edition's catalog
//    route (text-route.json) and converts it to USJ with tools/verse-text if needed.
const pin = cfg.pins.releases[edition.text];
const usj = await json('cache', 'releases', edition.text, pin.tag, `${book}.usj`);

// 4. The alignment files: files.json/text(dataset, path) gives a file of a bcv-commons dataset at
//    its pinned revision, or null. A web app fetches
//    https://huggingface.co/datasets/<repo>/resolve/<revision>/<path>
const files = {
    text: (ds, path) => orNull(readFile(join(ROOT, 'cache', 'hf', ds, cfg.pins.huggingface[ds].revision.slice(0, 12), path), 'utf8')),
    async json(ds, path) {
        const t = await this.text(ds, path);
        return t === null ? null : JSON.parse(t);
    },
};

// 5. The song plan: the book file, and the chapter files c-1, c, c+1 (a release of this repo).
const bookPlan = await json('plan', book, `${book}.json`);
const pad = (n) => String(n).padStart(3, '0');
const docs = (await Promise.all([c - 1, c, c + 1].map((n) => orNull(json('plan', book, `${book}_${pad(n)}.json`))))).filter(Boolean);

// The library: the book once, then any chapter of it.
const bt = await loadBookText(cfg, edition, book, usj);
const al = await loadAlignment(files, edition, book, bt.fileHash, bt.chapterFingerprints);
const ctx = prepareBook({ cfg, edition, book, bt, al, bookPlan, vmap: await verseMap(files, edition), lexemes: await lexemeKeys(files, book) });
const res = projectChapter(ctx, c, chapterPlan(docs));

console.log(`=== Style (alignment: ${al.kind}) ===\n${res.style}\n`);
console.log(`=== Lyrics (${res.chars} characters) ===\n${res.lyrics}`);
console.log(`=== Notes ===\n${res.notes}`);
