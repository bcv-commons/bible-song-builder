# bible-song-builder

Song lyrics for AI music services (Suno today) from **any Bible edition** that
[bcv-commons/bibles](https://github.com/bcv-commons/bibles) catalogs. The lyric words are the edition's own, verbatim.
Where the lines break, who sings them, the mood, and whether a chapter is sung or told come from the Hebrew and Greek
text, through bcv-commons data, so the same decisions carry over to every edition and language.

**Status: phase 3.** The code comes from [bsb2suno](https://github.com/BSB-publishing/bsb2suno), and for now it builds
the Berean Standard Bible only, with output identical to bsb2suno's. The work is split in two halves:

1. **The song plan** (`plan/<BOOK>/`, format in [`plan/SCHEMA.md`](plan/SCHEMA.md)), made once from the Hebrew/Greek
   and keyed to no edition: clause lines, speakers and their voices, stanza signals, text forms, chapter moods.
2. **The projection**, which lays a plan onto one edition's text through its alignment, and writes the lyrics. It
   is a JavaScript library (`js/`, no UI, no network access) and, as the reference it was ported from, the Python
   CLI. Both give the same output for all 1,189 BSB chapters.

Next: a Netlify app (its own repo) that uses the library to write the lyrics of any catalog edition in the browser,
just in time. bsb2suno will become a user of this repo.

See [`examples/`](examples/) for what it makes (RUT 1, PSA 22, PSA 23, PSA 136, EXO 15, EXO 39, LUK 1).

```
make setup                           # once: install, download the pinned data, build the cast table
python3 -m bible_song_builder RUT 1            # one chapter → output/RUT/RUT_001.lyrics.txt, .notes.txt, .json
python3 -m bible_song_builder PSA 23 136       # several
python3 -m bible_song_builder JON all          # a whole book
make plans                           # write the song plans of every book (plan/; the CLI writes them as needed)
make client                          # dist/config.json: config/ as JSON, for the JS library
make test-js                         # the JS library gives examples/ byte for byte
node js/sample/client.mjs PSA 23     # a sample client: one chapter's lyrics, Style and notes
make examples                        # rebuild examples/
make test                            # also checks that examples/ is current
make cast                            # rebuild the generated cast table
make cuts                            # where long chapters can be cut (output/cut-points.txt)
```

Needs Python ≥ 3.11 and `pyarrow`. `make setup` runs `pip install -e .` (editable, because the tool reads
`config/` from the repository) and downloads every input into `cache/` (git-ignored, about 100 MB) at
the revisions pinned in [`pins.json`](pins.json): the bcv-commons datasets on Hugging Face, and the BSB
text itself, the USJ release of [BSB-publishing/bsb2usfm](https://github.com/BSB-publishing/bsb2usfm/releases)
(one zip, checked by sha256): about 540 small files, fetched 8 at a time, which takes some minutes.
Without `make setup`, the first run downloads what it needs.

## What is in the repository, and what is generated

| | Where | In git |
|---|---|---|
| Code, tests, `Makefile`, `pins.json` | `bible_song_builder/`, `scripts/`, `tests/` | yes |
| Settings, and every hand decision | `config/` | yes |
| A few example chapters | `examples/` (rebuilt by `make examples`; the tests fail if stale) | yes |
| The song plan format | `plan/SCHEMA.md` | yes |
| The JS projection library, its tests, a sample client | `js/` | yes |
| The client config (generated) | `dist/config.json` (`make client`) | no |
| Song plans (generated) | `plan/<BOOK>/` (`make plans`, or the CLI when one is missing or stale) | no |
| Downloads; the generated cast table | `cache/` (`make setup`) | no |
| Lyrics, styles, notes; a copy of the cast table to browse | `output/` (every run) | no |

Nothing in `output/` is edited: it is rebuilt on every run. Every change goes in `config/`.

## The JS library

`js/` is the projection as a JavaScript library for clients (a web app, Node), with no UI and no network access.
A client fetches five things and passes them in: the config (`dist/config.json`), the edition's description
(name, language, licence, alignment layer, verse map), the edition's text of the book as USJ, the alignment files
(through a small `files.json(dataset, path)` function of its own), and the plan files of the book and the chapter.
Finding an edition in the bcv-commons/bibles catalog and fetching its text is the client's job.
[`js/sample/client.mjs`](js/sample/client.mjs) shows the calls; [`js/src/index.js`](js/src/index.js) lists them.

The library is a port of the Python projection (`bible_song_builder/__main__.py` and the modules it calls), kept
identical: `make test-js` builds `examples/` with it byte for byte. It uses the vendored JavaScript of
`tools/verse-text` 2.0.0 (`vendor/verse_text/js/`) for verse text, tokens and fingerprints. Node 20 or later.

## What it reads, per chapter

| Piece | Dataset (pinned in `pins.json`) | Used for |
|---|---|---|
| Structure | `bcv-commons/hebrew-clause-lines` v0.2 (Tanakh), `bcv-commons/greek-nt-clause-lines` v0.2 (NT) | line breaks, paragraph ends, quotations and speakers |
| Setting and forms | `bcv-commons/passage-facts` v0.3.3 | song / poetic lines / prose; refrains, acrostics, couplet halves, psalm headings; psalm types and purposes, deliveries (chapter moods) |
| Stanza breaks | `bcv-commons/clause-connectives` v0.1, `bcv-commons/clause-columns` v1.2 | where a long stanza is split |
| Lyric text | the BSB's own release (BSB-publishing/bsb2usfm, `BSB_usj.zip`, pinned by tag and sha256); read with the vendored `tools/verse-text` 2.0.0 | the words |
| The join | `bcv-commons/full-alignments-manual` v1.1, layer `eng_BSB+manual+bsb-tables` | which BSB token each Hebrew/Greek word (MACULA key) is rendered by |

The join uses the **full** BSB alignment, the publisher's own interlinear tables. It links every source
token, function words included, plus the words the editor supplied. Clause-line `words` are MACULA keys;
`_index/<BOOK>_keys.json` / `_fn_keys.json` of compact-alignments turn each `srcOrd` / `fnOrd` back into
a key. Spans are keyed by spine verse and read from the BSB verse the pinned verse map gives (Psalm titles
and the like). If no full layer exists, the compact alignment (content words only) is used. If neither
exists for the text, lines break at verse ends.

The book's text fingerprint has to match the alignment file name. If it doesn't, the latest aligned
version is used for the chapters whose chapter fingerprint matches ours (`_fingerprints.txt` in
compact-alignments-meta), and the other chapters break at verse ends. Nothing is aligned to text it
wasn't built on.

## The rules

**Line breaks.** Each clause line starts a new lyric line at the *earliest BSB token any of its words
aligned to*. That is "the target token aligned to the first aligned word", taken in BSB order rather than
Hebrew/Greek order. Source order fails: a Hebrew line usually opens with וַ "and", which BSB renders late
or folds away, and BSB reorders clauses. Taking the breaks in BSB order gives Ruth 1:6 as

```
When Naomi heard in Moab
that the LORD had attended to His people
by providing them with food,
she and her daughters-in-law prepared
to leave the land of Moab.
```

A clause line with no aligned word adds no break, so it stays with the line before. A verse always starts
a line. A line shorter than 3 words joins its neighbour in the same verse and voice (`lines.min_words`).

Three forms of the Hebrew text (passage-facts) add line starts, through the alignment:
- **Refrains:** each line the text repeats (`fm.tx.refrain`) is a line of its own.
- **Acrostics:** a new acrostic letter (`fm.tx.acrostic`) starts a line.
- **Couplet halves:** in Psalms, Proverbs and Job, a poetic verse also breaks where its second half starts
  (`fm.tx.halves`, the main accent; `lines.poetry`).

**Stanzas.** A stanza ends at the line holding the end of a clause line with `para_end` (Leningrad) or
`para_end_mam`. In an acrostic whose letters cover several verses (Psalm 119, Lamentations 3), each new letter
starts a stanza; the notes file names it (`119:9-12 · ב Beth`). A stanza over 12 lines (`stanzas.max_lines`)
is split at verse starts, where the Hebrew/Greek most clearly starts something new. The signals come from the
clause that opens the verse:

| Signal | Source | Weight |
|---|---|---|
| a new episode: Hebrew וַיְהִי / וְהָיָה with no actor, Greek καὶ ἐγένετο | clause-connectives `episode`, clause-columns | 3 |
| "and now", a Greek development connective (δέ, οὖν, τότε), a time clause | clause-connectives | 1 |
| a setting clause | clause-columns `line` | 1 |
| a new participant in narration | clause-columns `part_switch` | 1 |
| the narrator taking over from a speaker, or a speaker from the narrator | the quote data | 1 |

A split weighs one more stanza (cost 2) against the break it can use. The Greek has no paragraph marks, so in
the NT these signals alone shape the stanzas. Nothing here depends on the edition, so the stanzas, and the
cut points built on them, are the same in every language. An edition may add its own headings or paragraphs
as extra weight (`edition_heading_weight`, `edition_paragraph_weight`, `edition_paragraphs`). They are off for
BSB.

**Voices.** Where `quotation` is set, the line is sung by the speaker's *voice class*: `female`, `male`,
`group`, `female_group` or `divine`. Outside quotes it is the narrator, the persona's lead. Each class
becomes a tag that names a kind of voice, such as `[Female Vocal]`, `[Choir]` or `[Deep Male Vocal]`. A
tag never names a person, because Suno doesn't know who Naomi is. Who each tag stands for is listed in
the notes file (`Voices: [Female Vocal] Naomi, Ruth; [Female Choir] two daughters-in-law, the women`).

- **Where tags go.** A tag is written where the voice changes. `[Lead Vocal]` marks the return to the
  narrator.
- **Nested quotes.** A quote inside a speech (Eve quoting God, GEN 3:3) is sung by the outer speaker.
- **Where the classes come from.** The cast table, keyed by the clause lines' `speaker_id`, which is the
  same in every edition and language. See [Configuration](#configuration).

**Setting.** If passage facts set ≥ half the chapter as song (`fm.ms.song`, `qt.song`), the setting is
**song**. If song and poetic lines (`fm.ms.lines`, `fm.ed.*`, `fm.tr.poetry`) together reach half, it is
**poetry** (sung verses). Otherwise it is **prose** (narrative ballad). The setting only shapes the
sections; the style line comes from the book's profile, so a book sounds the same in every chapter.

**Sections.** Each stanza is a `[Verse n]`: a song verse, not a Bible verse (the notes file gives its
verse range). In a prose chapter, a stanza the facts set as song or poetry is a `[Bridge]` (Ruth's vow, the
Magnificat). A line the Hebrew/Greek repeats in its chapter (`fm.tx.refrain`) is a `[Chorus]`, e.g.
"And there was evening, and there was morning" in Genesis 1, in every edition alike. Where the refrain comes
back inside one stanza (Psalm 136), the stanza stays whole as call and response: `[Lead Vocal]` / `[Choir]`.
`layout.toml` sets the chorus source (the text's refrains, or the edition's repeated lines), its style, and
which section tags are written (all, only `[Chorus]`/`[Bridge]`, or none).

**Writing.** Nothing is shortened, paraphrased or added. The notes file gives each section's verse
range, the superscription and the psalm-heading terms (`fm.ps.*`: for the leader, the instruments, the
tune), the selahs and any one-letter-per-verse acrostic (all noted, not sung), the credits, and a warning when the lyrics run past
`--max-chars` (default 5000), so you know to shorten them. Any shortening done later should be listed
there.

## Configuration

All choices of sound live in `config/`. The files are meant to be edited by hand by anyone: the
settings are TOML files with a comment on every setting, and the cast is a spreadsheet. Everything is
keyed so that it carries over to other books, editions and languages.

| File | Edit with | Keyed by | Holds |
|---|---|---|---|
| [`books/<BOOK>.toml`](config/books/) | any text editor | book, chapter | a book's profile, lead singer and (optional) own style line; a chapter's mood or style (`[chapters.23]`). Books without a file use `_default.toml` |
| [`profiles.toml`](config/profiles.toml) | any text editor | profile name | style line, Suno persona names (`persona.female` / `persona.male`), the tag for each voice type, the words each mood adds |
| [`cast.csv`](config/cast.csv) | Excel, LibreOffice, Google Sheets | `speaker_id` (source data) | the speakers whose voice or name is set by hand |
| [`cast-rules.toml`](config/cast-rules.toml) | any text editor | none | the rules that give speakers their voice |
| [`layout.toml`](config/layout.toml) | any text editor | none | the defaults: text (word counting, line-start punctuation), setting codes, lines, stanzas, section tags, chorus, psalm marks, length limits |
| [`moods.toml`](config/moods.toml) | any text editor | none | which cue (psalm heading, song in narrative, psalm type or purpose, the commentators, speech delivery) gives a chapter which mood; which Hebrew term gives which mood; moods inside a chapter |
| [`editions.toml`](config/editions.toml) | any text editor | edition | the edition's text fixes, style suffix, own song choices and personas, and any layout setting |
| [`languages.toml`](config/languages.toml) | any text editor | ISO 639-3 code | the edition language's words for trimming speaker names and spotting groups; the Hebrew letter names |

Every output file says which setting made it: a chapter's notes file ends its style line with
"To change: config/books/PSA.toml, [chapters.23]".

A layout setting is looked up in three layers, and the later one wins:

1. `layout.toml`, the defaults;
2. `languages.toml [<iso>.layout]`, for every edition in that language (e.g. `count = "characters"` for Chinese);
3. `editions.toml [<EDITION>.layout]`, for that edition.

A choice read from the Hebrew/Greek stays in the code, because it holds for every edition. A choice read
from an edition's words or layout is a setting.

A mistake in a file (a misspelt profile, an unknown voice or fix, a broken line) stops the run with the file,
the row or book, and what is allowed.

**Profiles.** A profile is chosen per book, never per chapter. In Suno, save one persona per profile
and lead, then type its name into `profiles.toml` (`persona.female = "My Country F"`). The notes
file shows which persona to select. `--profile` / `--lead` override a book for one run.

**Cast.** The full cast table is generated from the data: one row per speaker (1,448), with its
`voice`, the rule that set it (`basis`), a `name`, the Hebrew/Greek word naming it (`source`), how many
`words` it speaks, its `books`, and the edition's own name for it (`label_BSB`). It is built into
`cache/` by `make setup`, and again by itself whenever the pins or the rules change; each run writes a
copy to `output/cast.csv` to browse.

Hand decisions go in [`config/cast.csv`](config/cast.csv), with four columns: `speaker_id`, `voice`
(`narrator`, `female`, `male`, `group`, `female_group`, `divine`), `name` and `note`. Find the speaker's id
in `output/cast.csv`, add a row, save as CSV (UTF-8). Seven rows are there now, e.g. Wisdom in Proverbs is
female. A row here always wins over the rules, and `make cast` reports when the rules change a voice.

The rules in `cast-rules.toml` read Hebrew/Greek words, not English:

- **group:** several people named (`speaker_members`, or several lemmas), or a word like עַם / πᾶς naming
  the speaker;
- **divine:** at least 80% of the speaker's quotes carry passage-facts' `divine` flag (the LORD, God, Jesus,
  the Spirit);
- **the speaking verb:** the verb that introduces the speaker. A plural verb means a group, וַתֹּאמֶר "she
  said" a woman (Acsah, Balaam's donkey). Gender is read from the Hebrew and Aramaic only, because a Greek
  participle agrees with its noun ("a voice saying" is feminine like φωνή);
- **female:** the head word naming the speaker is a word for a woman (אִשָּׁה, בַּת, γυνή, μήτηρ ...) or a
  woman's name (רוּת, Μαρία ...);
- **male:** otherwise.

The build also reads the edition's names for plural speakers ("the Levites", "the women"), using
`languages.toml`. It then stores the result by speaker, so another edition inherits it.

## Output

For each chapter, in `output/<BOOK>/`:

| File | What it is | In Suno |
|---|---|---|
| `<BOOK>_<CCC>.lyrics.txt` | the lyrics, with section and voice tags | paste whole into **Lyrics** |
| `<BOOK>.style.txt` | the book's style line, the same for every chapter | paste into **Style of Music** |
| `<BOOK>_<CCC>.style.txt` | only where the chapter has its own style (see below); use it instead | paste into **Style of Music** |
| `<BOOK>_<CCC>.notes.txt` | the persona to pick, the voices (tag → speakers), the sections and their verses, psalm headings, selah, acrostic letters, length warnings, which style file applies and why, and the credits | not pasted |
| `<BOOK>.notes.txt` | which chapters of the book have their own style, and why | not pasted |
| `<BOOK>_<CCC>.json` | the same lyrics with every line's verse, BSB token, quotation, speaker (id, label, voice class) and clause segment; the profile, style and mood, the text fingerprint, the alignment file and the pins | |

**Chapter styles.** A book keeps one style. A chapter gets its own only where the Hebrew/Greek, or a
scholarly reading of it, says how it sounds. Its style is then the book's style plus a few words for the
mood. The cues, in the order they win when they disagree (`sources` in `config/moods.toml`):

- **A psalm heading** that names the kind of piece: תְּפִלָּה a prayer (17, 86, 90, 102, 142, HAB 3),
  תְּהִלָּה praise (145), לְתוֹדָה thanksgiving (100), שִׁיר יְדִידֹת a love song (45), the sabbath (92),
  שִׁיר הַמַּעֲלוֹת a song of ascents (pilgrimage, 120–134); and הַלְלוּ יָהּ in the text (praise, 15 psalms).
  The instruments a heading names (בִּנְגִינוֹת strings, הַנְּחִילוֹת flutes) are added too.
- **A song in narrative**: the Masoretic song layout over most of a chapter in a book that is not song
  (EXO 15, DEU 32, JDG 5, 2SA 22, 1CH 16). Lists in song layout (JOS 12, EST 9) are not songs.
- **A psalm's type**, as the Tyndale Open Study Notes name it (passage-facts `fm.gn.*`, named by Hebrew
  terms: `tefillah_tsarah` a prayer in distress → lament, `tehillah` → praise, `todah` → thanksgiving,
  `mivtach` → trust, `chokhmah` → wisdom, `melekh` → royal …), where it covers at least half the psalm.
  Where the notes name more than two types for one psalm (Ps 119: five), they give none.
- **A psalm's purpose**, as Scriptura's Psalms: Layer by Layer states it (`fm.pu.*`, the same terms).
- **What the classical Hebrew commentators call the psalm** (Radak, Meiri, Rashi, Ibn Ezra, Malbim,
  Metzudat David), in their own words: תפלה prayer, שבח praise, הודאה thanksgiving (bcv-commons
  `hebrew-commentary-terms`, by rule, and `-model`, read by a model). Each term is matched to a root in
  `[commentary.roots]`; the mood most commentators agree on is taken.
- **Delivery**: speech delivered one way (passage-facts `delivery`) covers at least 40% of the
  chapter: a lament (EZK 19, 27, 32), a prayer (1KI 8, NEH 9, JON 2), anger (MAT 23).

With these, 135 of the 150 psalms have a mood (49 from the headings alone). The general heading terms
(a psalm, a song, a maskil) and the grammar of a psalm were tested as cues and are not used: they do not
tell a lament from praise reliably. A chapter whose mood comes from Tyndale, Scriptura or the
commentators credits them in its notes file.

**Moods inside a chapter.** Where the Hebrew/Greek words of most of a section mark a feeling, the
section opens with a tag after its section label, such as `[Mood: anguished]`. The tag is written only
where the feeling changes, and Suno sings the section in that mood within the chapter's style. The
feelings are the 9 families of passage-facts, each named by a Hebrew head word: שָׂמַח joy, בָּכָה
grief, יָרֵא fear and awe, אַף anger, בּוֹשׁ shame, בָּטַח trust, צָרָה distress, אָהֵב love, שָׂנֵא contempt.
They come from passage-facts `mood` facts (by rule) and from `passage-moods-model` (read by a model).
That gives tags in 337 of the 1,189 chapters. The notes file lists each section's mood and its
source, marks model readings "model-read", and credits the datasets. The words of each tag are in
`config/profiles.toml` (`[families]`, and `family_tag` for its form); `config/moods.toml`
`[section_moods]` turns this on or off, or turns off the model's part only.

The tags stay English, for Suno. The notes also name each family in the edition's own words: its most common
rendering in the book of the family's head lexemes ("md.tsarah צָרָה “trouble”" in the BSB Psalms; a Spanish
edition gives its Spanish word). The head lexemes are Strong's numbers in `config/moods.toml`
`[family_lexemes]`, Hebrew and Greek. The edition's words come through its alignment and the lexeme index of
compact-alignments, so no translation file is needed. Psalm heading terms are named the same way where the
edition's alignment covers the title; the BSB's does not yet, so they keep their English gloss.

**Model-made data.** Two inputs are a language model's readings with no human check:
`hebrew-commentary-terms-model` and `passage-moods-model`. Every chapter that uses them says so in its
notes file.

`config/moods.toml` says which cue gives which mood. `config/profiles.toml` (`[moods]`,
`[instruments]`, and per profile) says which words each mood adds; `""` turns a mood off.

## The text and its repairs

The text is the BSB's published USJ (bsb2usfm release v5.20). It is checked against the fingerprints
the alignments were built on. Three narrow repairs, in `bible_song_builder/edition.py` and switched on per edition
in `editions.toml` (`fixes`), make it read as the aligned text does:

- `titles-in-d`: a psalm title paragraph (`\d`) holds the verse-1 marker (`\d \v 1 A Psalm of David`).
  The title is read as a title, not as verse 1. PSA only.
- `note-spaces`: the USJ export drops the space between a footnote and a following `\add` word
  (USFM `punishment\f …\f* \add is\add*` reads "punishmentis"), 144 places. The space is put back.
  Reported to bsb2usfm; the repair goes once a fixed release is pinned.
- `span-spaces`: some `\add` spans end in a space before punctuation (`\add his role \add*.`), 187
  places. That space is dropped.

With these, 65 of 66 books have exactly the aligned words, and 1,177 of 1,189 chapters match the
alignment. The 12 others fall back to verse-end line breaks (their notes file says so):

- EXO 26, NUM 25, JER 22, HAB 3, ACT 22, 2TI 1, JUD 1, whose aligned text differs from the BSB;
- SNG 1, 5, 6, 7, 8: the aligned text has the speaker labels ("The Friends", "The Bride") as verse words.
  The release has them as headings, which is right, so they are not sung.

The text used to come from bible.helloao.org. The release is the BSB's own text: it has the BSB's brackets
("[The sons of Aram:]") and none of helloAO's stray spaces ("Nevertheless , David") or footnotes merged
into verses.

## Licences

Code and settings: MIT (see [`LICENSE`](LICENSE)). The generated cast table, `examples/` and the lyric
sheets, built from bcv-commons data: CC BY-SA 4.0. The vendored `vendor/verse_text/` is CC0 (bcv-commons/bibles). The lyric text is the BSB
(public domain). The line and voice structure comes from CC BY-SA 4.0 data, so
credit bcv-commons when you publish lyric sheets. See [ATTRIBUTION.md](ATTRIBUTION.md).
