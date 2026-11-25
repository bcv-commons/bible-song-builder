// bible-song-builder, the projection (half 2): a song plan laid onto one edition's text through
// its alignment, giving lyrics, the Style line and notes. No UI and no network access: the client
// fetches the text, the alignment files, the plans and the config, and passes them in.
//
//   const cfg = new Config(configBundle);                       // dist/config.json
//   const bt = await loadBookText(cfg, edition, book, usj);      // the edition's USJ of the book,
//   //   or from text in any format: await bookText(edition, book, { verses, paragraphStarts, headingBefore, poetryVerses, titles, name })
//   const al = await loadAlignment(files, edition, book, bt.fileHash, bt.chapterFingerprints, { partial: bt.partial });
//   const vmap = await verseMap(files, edition);
//   const ctx = prepareBook({ cfg, edition, book, bt, al, bookPlan, vmap });
//   const docs = spineChapters(vmap, book, 23).map(...);        // the plan files it needs
//   const res = projectChapter(ctx, 23, chapterPlan(docs));
//   res.lyrics, res.style, res.notes
//
// `files` is the client's: async json(dataset, path) / text(dataset, path), a file of a pinned
// bcv-commons dataset, or null when it does not exist.
export { Config } from './config.js';
export { ConfigError } from './util.js';
export { bookText, loadBookText, usjLayout } from './edition.js';
export { Alignment, lexemeKeys, loadAlignment, verseMap, spineChapters, spineToEdition } from './align.js';
export { chapterPlan, prepareBook, projectChapter, chapterFiles, bookFiles, chapters, withDefaults, VERSION } from './project.js';
