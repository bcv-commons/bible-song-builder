"""Half 1: the song plan of a book, read from the Hebrew/Greek only (plan/SCHEMA.md).

    python -m bible_song_builder.plan RUT PSA      # write plan/RUT/, plan/PSA/
    python -m bible_song_builder.plan all          # every book

A plan does not depend on any edition: it is keyed to MACULA word keys and spine verses
(WLC / Nestle 1904 numbering). Half 2 (``__main__``) reads only the plan, the edition's text
and the alignment. The plan reads no setting an edition or language can change
(layout.toml layers, profiles, editions.toml): it keeps the source data those settings act on,
trimmed to what half 2 reads. One exception, because it needs the whole book: the chapter moods
use the [setting] codes of layout.toml itself.

Files, in ``plan/<BOOK>/``:
  <BOOK>.json           the book: chapter moods, speakers (rule voice, words naming them), credits
  <BOOK>_<CCC>.json     one spine chapter: clause rows, stanza signals, form and quote facts,
                        mood spans. Half 2 reads chapters c-1, c and c+1 for edition chapter c,
                        and any other the verse map moves a verse from (align.spine_chapters).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from . import __version__, cast, config, fetch, moods, structure, textforms
from .edition import BOOKS

SCHEMA = "1.1"
ROOT = Path(__file__).resolve().parent.parent
PLAN_DIR = ROOT / "plan"

# clause-row fields half 2 reads (lines.py), kept only where they are set
ROW_FIELDS = ("chapter", "verse", "seg", "line", "words", "quotation", "speaker_id", "para_end", "para_end_mam",
              "depth", "clause_key")
ALWAYS = {"chapter", "verse", "seg", "words"}
# passage-facts fields half 2 reads (textforms.chapter_marks, structure.setting_verses)
FACT_FIELDS = ("kind", "value", "first", "last", "layout", "halves", "letters")
REFRAIN_FIELDS = ("id", "words", "occurrences")


def stamp() -> str:
    """What a plan depends on: the pins, the config half 1 reads and the code that reads it."""
    h = hashlib.sha256()
    here = Path(__file__).resolve().parent
    for p in (fetch.ROOT / "pins.json", config.CONFIG / "moods.toml", config.CONFIG / "cast-rules.toml",
              config.CONFIG / "layout.toml", *(here / f for f in ("plan.py", "structure.py", "cast.py",
                                                                  "moods.py", "textforms.py", "config.py"))):
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def _row(r: dict) -> dict:
    r = dict(r, speaker_id=cast.speaker_id(r), clause_key=structure.clause_key(r))
    return {k: r[k] for k in ROW_FIELDS if k in ALWAYS or r.get(k)}


def split_at_quote_starts(rows: list[dict]) -> list[dict]:
    """A clause row in which a quote starts after its first word (the source puts "ὅτι Τεθέαμαι" in
    one row, the quote starting at Τεθέαμαι, John 1:32) is split there: the words from the quote's
    first word on are their own row, sung by the quote's speaker. A quote is known by its rows'
    ``quotation``, the key of its first word. The new row has no clause_key (it starts no clause)
    and takes the row's paragraph end."""
    speaker = {}
    for r in rows:
        if r.get("quotation"):
            speaker.setdefault(r["quotation"], r.get("speaker_id"))
    out = []
    for r in rows:
        cut = next((i for i, k in enumerate(r["words"]) if i > 0 and k in speaker and r.get("quotation") != k), None)
        if cut is None:
            out.append(r)
            continue
        a = {k: v for k, v in r.items() if k not in ("para_end", "para_end_mam")}
        a["words"] = r["words"][:cut]
        q = r["words"][cut]
        b = {k: v for k, v in r.items() if k not in ("clause_key", "quotation", "speaker_id")}
        b["words"] = r["words"][cut:]
        b["quotation"] = q
        if speaker[q]:
            b["speaker_id"] = speaker[q]
        out += [a, {k: b[k] for k in ROW_FIELDS if k in b}]
    return out


def _fact(n: int, f: dict, labels: dict[str, str]) -> dict:
    out = {"n": n, **{k: f[k] for k in FACT_FIELDS if f.get(k) is not None}}
    if f.get("value") == "fm.tx.refrain":
        out.update({k: f[k] for k in REFRAIN_FIELDS if f.get(k) is not None})
    if f.get("value", "").startswith("fm.ps.") and f["value"] in labels:
        out["label"] = labels[f["value"]]       # its description, for the notes (passage-facts codes.tsv)
    return out


def _touches(f: dict, c: int) -> bool:
    return int(f["first"][2:5]) <= c <= int(f["last"][2:5])


def _runs_touch(runs: list, c: int) -> bool:
    return any(r[0] == c for r in runs)


def build(book: str) -> tuple[dict, dict[int, dict]]:
    """(the book's plan, {spine chapter: its plan})."""
    rows = structure.clause_lines(book, set(range(0, 200)))
    facts = structure.passage_facts(book)
    hf = fetch.pins()["huggingface"]
    lines_ds = structure.lines_dataset(book)
    spine = sorted({(r["chapter"], r["verse"]) for r in rows})
    span_rows, readings = moods.reading_spans(book, spine)
    used = [lines_ds, "passage-facts", "clause-connectives", "clause-columns", "passage-moods-model",
            *structure.COMMENTARY_DATASETS, *(["passage-mood-spans-model"] if span_rows or readings else [])]
    infos = cast.gather(rows, facts)
    speakers = {sid: {"voice": cast.rule_voice(infos.get(sid) or cast.SpeakerInfo())[0], **refs}
                for sid, refs in cast.speaker_refs(rows).items()}
    book_doc = {
        "schema": SCHEMA, "kind": "book", "book": book,
        "testament": "nt" if book in structure.NT_BOOKS else "ot", "lines_dataset": lines_ds,
        "bible-song-builder": __version__, "stamp": stamp(),
        "pins": {d: {k: hf[d][k] for k in ("repo", "tag", "revision", "licence")} for d in used},
        "chapters": sorted({r["chapter"] for r in rows}),
        "moods": [{"chapter": c, "mid": list(mid), "mood": m.mood, "basis": m.basis, "evidence": m.evidence,
                   "instruments": list(m.instruments)}
                  for c, mid, m in moods.chapter_moods(book, facts, rows, config.toml("layout.toml"))],
        "readings": readings,
        "speakers": speakers,
        "sources": moods.scholarly_sources(),
    }

    labels = textforms.codes()
    signals = structure.clause_signals(book)
    mood_facts, model_moods = moods.mood_spans(book, facts, spine, rows)
    chapters = {}
    for c in book_doc["chapters"]:
        ch_rows = split_at_quote_starts([_row(r) for r in rows if r["chapter"] == c])
        keys = [r["clause_key"] for r in ch_rows if r.get("clause_key")]
        chapters[c] = {
            "schema": SCHEMA, "kind": "chapter", "book": book, "chapter": c,
            "rows": ch_rows,
            "signals": {k: {f: v for f, v in signals[k].items() if v is not None}
                        for k in dict.fromkeys(keys) if k in signals},
            "facts": [_fact(n, f, labels) for n, f in enumerate(facts)
                      if f.get("kind") in ("form", "quote") and _touches(f, c)],
            "mood_facts": [m for m in mood_facts if _runs_touch(m["verses"], c)],
            "model_moods": [m for m in model_moods if _runs_touch(m["verses"], c)],
            "mood_spans": [m for m in span_rows if _runs_touch(m["verses"], c)],
        }
    return book_doc, chapters


def _dump(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n"


def write(book: str, root: Path = PLAN_DIR) -> Path:
    book_doc, chapters = build(book)
    d = root / book
    d.mkdir(parents=True, exist_ok=True)
    for c, doc in chapters.items():
        (d / f"{book}_{c:03d}.json").write_text(_dump(doc), encoding="utf-8")
    for old in d.glob(f"{book}_*.json"):                  # chapters an earlier build had and this one has not
        if int(old.stem.split("_")[1]) not in chapters:
            old.unlink()
    (d / f"{book}.json").write_text(_dump(book_doc), encoding="utf-8")    # last: it marks the plan complete
    return d


def ensure(book: str, root: Path = PLAN_DIR) -> None:
    """Write the book's plan if it is missing or was built from other pins, config or code."""
    p = root / book / f"{book}.json"
    if p.exists():
        doc = json.loads(p.read_text(encoding="utf-8"))
        if doc.get("schema") == SCHEMA and doc.get("stamp") == stamp():
            return
    print(f"writing the song plan of {book} (plan/{book}/) ...", file=sys.stderr)
    write(book, root)


# ---- reading a plan (half 2) ----

def load_book(book: str, root: Path = PLAN_DIR) -> dict:
    doc = json.loads((root / book / f"{book}.json").read_text(encoding="utf-8"))
    if doc.get("schema", "").split(".")[0] != SCHEMA.split(".")[0]:
        raise config.ConfigError(f"plan/{book}/{book}.json: schema {doc.get('schema')}, this code reads {SCHEMA}")
    return doc


class ChapterPlan:
    """What half 2 reads for one edition chapter: the plans of the spine chapters its verses come
    from (align.spine_chapters: c-1, c, c+1, and further ones a verse map moves a verse from)."""

    def __init__(self, docs: list[dict]):
        self.rows = [r for d in docs for r in d["rows"]]
        self.signals: dict[str, dict] = {}
        for d in docs:
            self.signals.update(d["signals"])
        self.facts = _union(docs, "facts", "n")
        self.mood_facts = _union(docs, "mood_facts", "n")
        self.model_moods = _union(docs, "model_moods", "m")
        self.mood_spans = _union(docs, "mood_spans", "s")     # passage-mood-spans-model (schema 1.1)
        # descriptions of the psalm-heading codes (passage-facts codes.tsv)
        self.labels = {f["value"]: f["label"] for f in self.facts if "label" in f}


def _union(docs: list[dict], part: str, key: str) -> list[dict]:
    seen: dict[int, dict] = {}
    for d in docs:
        for x in d.get(part, []):
            seen.setdefault(x[key], x)
    return [seen[k] for k in sorted(seen)]


def load_chapter(book: str, chapter: int, root: Path = PLAN_DIR, vmap: dict | None = None) -> ChapterPlan:
    from . import align
    docs = []
    for c in align.spine_chapters(vmap or {}, book, chapter):
        p = root / book / f"{book}_{c:03d}.json"
        if p.exists():
            docs.append(json.loads(p.read_text(encoding="utf-8")))
    return ChapterPlan(docs)


def edition_moods(book_doc: dict, to_ed) -> dict[int, moods.Mood]:
    """Edition chapter -> the chapter mood of the plan (a spine chapter goes to the edition chapter
    its middle verse is in)."""
    out = {}
    for m in book_doc["moods"]:
        e = to_ed(tuple(m["mid"]))
        if e is not None:
            out[e[0]] = moods.Mood(m["mood"], m["basis"], m["evidence"], tuple(m["instruments"]))
    return out


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    books = BOOKS if args == ["all"] else [b.upper() for b in args]
    for b in books:
        d = write(b)
        n = len(list(d.glob(f"{b}_*.json")))
        size = sum(p.stat().st_size for p in d.glob("*.json"))
        print(f"{d.relative_to(ROOT)}/  {n} chapters, {size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
