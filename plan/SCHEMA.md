# Song plan format, schema 1.0

A song plan is half 1 of bible-song-builder: what the Hebrew/Greek says about how a chapter is sung, keyed to the
source and to no edition. Half 2 (the projection, `bible_song_builder/__main__.py`, later the JavaScript library)
reads only the plan, the edition's text and the alignment, and writes the lyrics, the style line and the notes.

Plans are written by `python3 -m bible_song_builder.plan <BOOK>… | all` (`make plans`), and by the CLI when a book's
plan is missing or stale. They are generated (git-ignored); only this file is in git. The code is
`bible_song_builder/plan.py`.

## Versions

`schema` is `MAJOR.MINOR`. A reader accepts any plan with its own MAJOR. MINOR grows when fields are added that old
readers may ignore; MAJOR grows when a field is removed or changes meaning.

| Schema | Change |
|---|---|
| 1.0 | First version (phase 2) |

## Keys and numbering

- **Word keys** are MACULA keys, `BBCCCVVVWWW` plus a digit for the Hebrew morpheme (OT 12 digits, NT 11):
  book `[0:2]`, chapter `[2:5]`, verse `[5:8]`. The alignments link these keys to edition tokens.
- **Chapters and verses** are spine numbers (WLC for the OT, Nestle 1904 for the NT). Half 2 maps them to the
  edition's numbers through the edition's verse map. A verse is `[chapter, verse]`; a verse list is a list of
  **runs** `[chapter, first verse, last verse]` (every verse in between that has clause lines).
- **Clause keys** (`clause_key`) are the keys clause-connectives and clause-columns use: the Hebrew `clause_key`,
  or for Greek the segment's first word.

## Files

```
plan/<BOOK>/<BOOK>.json         the book
plan/<BOOK>/<BOOK>_<CCC>.json   one spine chapter (CCC: three digits; PSA_119)
```

UTF-8 JSON, compact, one line. The book file is written last: if it is there, the book's plan is complete. Whole
Bible: 1,255 files, 33 MB, about 4.1 MB gzipped; a chapter is at most 130 KB (PSA 119, 15 KB gzipped).

**For edition chapter c, half 2 reads the chapter files c-1, c and c+1**, those that exist, and joins them: rows in
file order, `facts`, `mood_facts` and `model_moods` by their index (`n`, `m`) with duplicates dropped, `signals` as
one map. A verse map can move a verse into the chapter before or after, so the neighbours are needed.

## The book file

| Field | Type | Meaning |
|---|---|---|
| `schema` | string | `"1.0"` |
| `kind` | string | `"book"` |
| `book` | string | USFM code, e.g. `"PSA"` |
| `testament` | string | `"ot"` or `"nt"` |
| `lines_dataset` | string | `hebrew-clause-lines` or `greek-nt-clause-lines` |
| `bible-song-builder` | string | version of the code that wrote it |
| `stamp` | string | hash of the pins, the config half 1 reads and its code; a plan with another stamp is rebuilt |
| `pins` | object | dataset → `{repo, tag, revision, licence}`, for every source dataset the plan comes from. The credit lines are written from these |
| `chapters` | [int] | the spine chapters that have a chapter file |
| `moods` | [object] | the chapter moods (below), in the order they were found |
| `speakers` | object | speaker_id → speaker (below), in the order the speakers first occur |
| `sources` | object | passage-facts `sources.tsv` id → the credit it asks for, for the scholarly sources a mood can name (`tyndale`, `scriptura`) |

**A chapter mood:** where the source gives a chapter a reason for its own style (`moods.py`: a heading term, a song
in narrative, the psalm's type or purpose, the commentators, the delivery).

| Field | Type | Meaning |
|---|---|---|
| `chapter` | int | spine chapter |
| `mid` | [int, int] | its middle verse: the mood goes to the edition chapter this verse maps to (the later one wins) |
| `mood` | string or null | e.g. `"lament"`; null when only instruments are named |
| `basis` | string | `heading`, `song`, `type`, `purpose`, `commentary` or `delivery` |
| `evidence` | string | what in the source gave it (English, for the notes) |
| `instruments` | [string] | instruments a heading names, e.g. `["strings"]` |

**A speaker:**

| Field | Type | Meaning |
|---|---|---|
| `voice` | string | voice class by `config/cast-rules.toml` alone. Half 2 uses the cast table's voice where it has one |
| `named` | [[keys, n]] | the word keys naming the speaker (`speaker_name_ref`), each different list with how many clause rows give it, in first-occurrence order |
| `described` | [[keys, n]] | the same for the words introducing them (`speaker_ref`) |

Half 2 finds the edition's words for these keys, per edition chapter: the commonest `named` phrase of the chapter
(counted by `n`) is the speaker's label there, else the commonest `described` one; where the chapter has neither,
the phrase at the speaker's **main naming place** (`lines.main_naming`): among the entries of this book, the `named`
one with the largest `n`, else the `described` one; else a `named` one in another book (the Greek names a speaker
where they are first named, also in another book). Ties go to the earlier one. Keys are lists also for the Greek
(`speaker_name_ref` is one key there; plans before 0.3.1 split it into digits).

## The chapter file

| Field | Type | Meaning |
|---|---|---|
| `schema`, `kind` (`"chapter"`), `book`, `chapter` | | as above; `chapter` is the spine chapter |
| `rows` | [object] | the clause lines of the chapter, in text order (below) |
| `signals` | object | clause key → stanza signals of that clause |
| `facts` | [object] | passage-facts `form` and `quote` facts whose chapters include this one |
| `mood_facts` | [object] | passage-facts `mood` facts (`md.*`) covering a verse of this chapter |
| `model_moods` | [object] | passage-moods-model rows covering a verse of this chapter (model output, no human check) |

**A row** is one clause line of hebrew-clause-lines / greek-nt-clause-lines, trimmed to what half 2 reads. Fields
that are empty, false or zero are left out, except the first four.

| Field | Meaning |
|---|---|
| `chapter`, `verse`, `seg` | spine chapter and verse; the segment number in the verse |
| `words` | its word keys |
| `line` | its line number in the segment |
| `quotation` | quotation id (`q00016`; a nested quote `q00016.t1`); absent for the narrator |
| `speaker_id` | who speaks it (the source's id, or the Hebrew/Greek word naming the speaker) |
| `para_end`, `para_end_mam` | a paragraph of the Leningrad Codex / the MAM ends with this line |
| `depth` | how deep the clause is embedded (absent: a top-level clause) |
| `clause_key` | its clause key |

**Signals** (stanza breaks, `lines.break_strength`): `link` (clause-connectives, e.g. `episode`, `and_now`), `line`
and `part_switch` (clause-columns). Greek καὶ ἐγένετο and Hebrew וַיְהִי with no actor are given `link: "episode"`.

**A fact:** `n` (its index in the book's passage-facts file), `kind`, `value`, `first`, `last` (word keys), and,
where the fact has them:
- `layout`: `"list"` marks a list set in song layout (not a song);
- refrains (`fm.tx.refrain`): `id`, `words` (how many words), `occurrences` (`[[first, last], …]`);
- `halves` (`fm.tx.halves`): `[[first, last], [first, last]]`, A and B;
- `letters` (`fm.tx.acrostic`): `[[first, last, letter], …]`;
- `label` (`fm.ps.*`): the code's description in passage-facts `codes.tsv`, for the notes.

All form and quote facts are kept, not only the ones today's settings use, because which codes count as song or
poetry is a layout setting (`layout.toml [setting]`) that an edition can change.

**A mood fact:** `n`, `family` (`md.*`), `head` (its Hebrew/Greek head word), `of_god` (true, or absent: a verse
holding its marked words names God, or God or an angel speaks in the span or the verse after it; `moods._OfGod`),
`verses` (runs over the whole span, also outside this chapter). **A model mood:** `m` (its row index for the book),
`moods` (`[{family, head, of_god}]`, strongest first; half 2 weighs them by rank, `moods.toml [section_moods] model_weights`), `verses` (runs).

## What is in the plan and what is not

The plan holds only what the Hebrew/Greek data says, and reads only settings that no edition or language can change:
`config/moods.toml` (chapter moods), `config/cast-rules.toml` (rule voices), and `layout.toml [setting]` itself
(not its language or edition layers) for the "song in narrative" chapter mood, which needs the whole book.

Everything an edition, a language or a user can set is applied in half 2:
- every `layout.toml` setting (with its layers): line breaks, refrain and acrostic thresholds, which codes make a
  song or poetry, stanzas, chorus;
- profiles and the style line, the `config/books/<BOOK>.toml` chapter overrides, section-mood words;
- the cast table (`cache/cast/cast.csv` with `config/cast.csv` over it), which wins over the plan's rule voice.

A change to `moods.toml` or `cast-rules.toml` therefore needs the plans rebuilt (the stamp does this for the CLI).

## Licence

Plans are derived from CC BY-SA 4.0 data (the clause lines, passage facts and their UBS sources), so they are
published under CC BY-SA 4.0. The `pins` and `sources` in each book file give the credits.
