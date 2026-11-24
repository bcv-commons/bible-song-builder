// Reading the inputs from this repository's folders, for Node (the tests, the CLI, the sample):
// the dataset files Python downloaded into cache/, the BSB text release, the plans and the config
// bundle. Nothing is downloaded: a file that is not there is "not found".
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';

async function readOrNull(path) {
    try {
        return await readFile(path, 'utf8');
    } catch (e) {
        if (e.code === 'ENOENT') return null;
        throw e;
    }
}

/** files for loadAlignment / verseMap: cache/hf/<dataset>/<revision[:12]>/<path> */
export function cacheFiles(root, pins) {
    const text = (ds, path) => readOrNull(join(root, 'cache', 'hf', ds, pins.huggingface[ds].revision.slice(0, 12), path));
    return {
        text,
        async json(ds, path) {
            const t = await text(ds, path);
            return t === null ? null : JSON.parse(t);
        },
    };
}

export async function readJson(path) {
    return JSON.parse(await readFile(path, 'utf8'));
}

/** The book's USJ from a pinned release in cache/releases/<name>/<tag>/ */
export async function releaseUsj(root, pins, release, book) {
    const pin = pins.releases[release];
    return readJson(join(root, 'cache', 'releases', release, pin.tag, `${book}.usj`));
}

export const bookPlan = (root, book) => readJson(join(root, 'plan', book, `${book}.json`));

/** The plan files of spine chapters c-1, c, c+1 that exist */
export async function chapterPlanDocs(root, book, chapter) {
    const docs = [];
    for (const c of [chapter - 1, chapter, chapter + 1]) {
        const t = await readOrNull(join(root, 'plan', book, `${book}_${String(c).padStart(3, '0')}.json`));
        if (t !== null) docs.push(JSON.parse(t));
    }
    return docs;
}
