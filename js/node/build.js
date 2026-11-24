// Build a book's chapters from this repository's folders (what the CLI and the tests share).
import { join } from 'node:path';
import { Config, chapterFiles, chapterPlan, bookFiles, chapters, lexemeKeys, loadAlignment, loadBookText, prepareBook, projectChapter, verseMap } from '../src/index.js';
import { bookPlan, cacheFiles, chapterPlanDocs, readJson, releaseUsj } from './files.js';

export async function loadConfig(root) {
    return new Config(await readJson(join(root, 'dist', 'config.json')));
}

/** {file name: text} for the book's files and the given chapters ('all' or numbers) */
export async function buildBook(root, cfg, editionName, book, wanted = 'all', args = {}) {
    const pins = cfg.pins;
    const edition = { name: editionName, ...pins.editions[editionName] };
    const files = cacheFiles(root, pins);
    const bt = await loadBookText(cfg, edition, book, await releaseUsj(root, pins, edition.text, book));
    const al = await loadAlignment(files, edition, book, bt.fileHash, bt.chapterFingerprints);
    const ctx = prepareBook({ cfg, edition, book, bt, al, bookPlan: await bookPlan(root, book), vmap: await verseMap(files, edition), lexemes: await lexemeKeys(files, book), args });
    const out = { ...bookFiles(ctx) };
    for (const c of wanted === 'all' ? chapters(ctx) : wanted) {
        const res = projectChapter(ctx, c, chapterPlan(await chapterPlanDocs(root, book, c)));
        Object.assign(out, chapterFiles(ctx, c, res));
    }
    return out;
}
