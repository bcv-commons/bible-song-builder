"""The cast table: who sings each speaker, built from the source data.

The table is generated, never edited: ``cache/cast/cast.csv``, rebuilt when the pins, the rules
(config/cast-rules.toml, languages.toml) or this code change. Hand decisions go in
config/cast.csv, which is laid over it (config.cast_table). Each run also writes the merged
table to ``output/cast.csv``, to look up a speaker's id.

Every speaker_id in the clause lines gets a row: its voice by the rules in cast-rules.toml, the
Hebrew/Greek word naming it (source), how many words it speaks, its books, and the edition's
name for it (label_<EDITION>). Labels of other editions already in the table are kept.

The edition's labels give one more rule, which only the build applies: a label holding one of
the languages.toml label_group / label_female_group words ("the women", "his brothers") makes the
speaker a group.
"""
from __future__ import annotations

import hashlib
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import align, cast, config, edition, fetch, lines, structure

STAMP = config.CAST_GENERATED.with_name("stamp.txt")


def stamp() -> str:
    """What the table depends on: the pins, the rules and the code that applies them."""
    h = hashlib.sha256()
    here = Path(__file__).resolve().parent
    for p in (fetch.ROOT / "pins.json", config.CONFIG / "cast-rules.toml", config.CONFIG / "languages.toml",
              here / "cast.py", here / "castbuild.py", here / "lines.py"):
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def ensure(edition_name: str = "BSB") -> None:
    """Build the table if it is missing or out of date (once; it reads every book)."""
    if config.CAST_GENERATED.exists() and STAMP.exists() and STAMP.read_text().strip() == stamp():
        return
    print("building the cast table from the data (once, after a change of pins or rules) ...", file=sys.stderr)
    build(edition_name)


def _fetch_book(edition_name: str, b: str) -> None:
    """Everything a book needs from the pinned data, downloaded into cache/ (read the way a run reads it)."""
    structure.clause_lines(b, {1})
    structure.passage_facts(b)
    bt = edition.load_book(edition_name, b)
    align.load(edition_name, b, bt.file_hash, bt.chapter_fingerprints)


def prefetch(edition_name: str = "BSB", books: list[str] | None = None, workers: int = 8) -> None:
    """Download the pinned files of all books several at a time (a first setup is ~540 files;
    one by one that takes many minutes). Files already in cache/ are not fetched again."""
    books = books or edition.books(edition_name)        # also unpacks the text release, once
    shared = [("passage-facts", "codes.tsv"), ("passage-facts", "sources.tsv"),
              ("passage-moods-model", "data/moods.parquet")] + [
             (d, "data/statements.parquet") for d in structure.COMMENTARY_DATASETS] + [(d, f"data/{t}.parquet") for d in structure.CLAUSE_SIGNAL_DATASETS
                                                  for t in ("hebrew", "greek-nt")]
    align.verse_map(edition_name)
    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(lambda x: fetch.hf(*x), shared))
    print(f"downloading the pinned data for {len(books)} books ({workers} at a time) ...", file=sys.stderr)
    with ThreadPoolExecutor(workers) as pool:
        for b, _ in zip(books, pool.map(lambda b: _fetch_book(edition_name, b), books)):
            print(b, file=sys.stderr, end=" ", flush=True)
    print(file=sys.stderr)


def build(edition_name: str = "BSB", only: list[str] | None = None) -> Path:
    """Build the table; ``only``: re-check just these books and keep the other rows."""
    prefetch(edition_name, only)
    rules = config.cast_rules()
    old = config._read_csv(config.CAST_GENERATED, "cache/cast/cast.csv")   # the last build, without overrides
    ed = fetch.pins()["editions"][edition_name]
    lw = config.language(ed["iso"])
    label_group = {w.lower() for w in lw.get("label_group", [])}
    label_fgroup = {w.lower() for w in lw.get("label_female_group", [])}

    info: dict[str, cast.SpeakerInfo] = defaultdict(cast.SpeakerInfo)
    words: Counter = Counter()
    books: dict[str, set] = defaultdict(set)
    labels: dict[str, Counter] = defaultdict(Counter)
    order = edition.books(edition_name)
    for b in only or order:
        rows = structure.clause_lines(b, set(range(200)))
        for sid, i in cast.gather(rows, structure.passage_facts(b)).items():
            info[sid].add(i)
        for r in rows:
            sid = cast.speaker_id(r) if r.get("quotation") else None
            if sid:
                words[sid] += len(r["words"])
                books[sid].add(b)
        bt = edition.load_book(edition_name, b)
        al = align.load(edition_name, b, bt.file_hash, bt.chapter_fingerprints)
        for sid, sp in lines.speaker_labels(cast.speaker_refs(rows), al, bt).items():
            if sp.label and sid in words:
                labels[sid][sp.label] += 1
        print(b, file=sys.stderr, end=" ", flush=True)
    print(file=sys.stderr)

    rows = []
    seen = set()
    for sid, n in words.most_common():
        i = info[sid]
        label = labels[sid].most_common(1)[0][0] if labels[sid] else ""
        voice, basis = cast.rule_voice(i, rules)
        if voice != "female_group" and label:
            lw_ = set(re.findall(r"[\w’'-]+", label.lower()))
            if lw_ & label_fgroup:
                voice, basis = "female_group", f"label:{edition_name}"
            elif voice != "group" and lw_ & label_group:
                voice, basis = "group", f"label:{edition_name}"
        prev = old.get(sid, {})
        row = {**prev,                                    # keeps other editions' label_ columns
               "speaker_id": sid, "voice": voice, "basis": basis, "name": label,
               "source": (i.names.most_common(1)[0][0] if i.names else
                          i.lemmas.most_common(1)[0][0] if i.lemmas else ""),
               "words": n, "books": " ".join(sorted(books[sid], key=order.index)),
               f"label_{edition_name}": label}
        if only and prev:          # a run on some books: keep what the whole Bible gave
            row.update({k: prev[k] for k in ("words", "books", "name", f"label_{edition_name}") if prev.get(k)})
        rows.append(row)
        seen.add(sid)
    for sid, prev in old.items():          # a partial run keeps every row it did not see
        if sid not in seen and only:
            rows.append(prev)
    rows.sort(key=lambda r: (-int(r.get("words") or 0), r["speaker_id"]))
    editions = sorted({k[6:] for r in rows for k in r if k.startswith("label_")} | {edition_name})
    path = config.write_cast(rows, editions)
    if not only:
        STAMP.write_text(stamp() + "\n")
    changed = [(r["speaker_id"], old[r["speaker_id"]]["voice"], r["voice"], r.get("name", ""))
               for r in rows if r["speaker_id"] in old and old[r["speaker_id"]]["voice"] != r["voice"]]
    if old and changed:
        print(f"{len(changed)} speakers changed voice since the last build:", file=sys.stderr)
        for sid, a, b, nm in changed[:15]:
            print(f"  {sid} {nm or ''}: {a} -> {b}", file=sys.stderr)
    c, w = Counter(), Counter()
    for r in rows:
        c[r["voice"]] += 1
        w[r["voice"]] += int(r.get("words") or 0)
    tot = sum(w.values()) or 1
    print(f"{len(rows)} speakers -> {path.relative_to(fetch.ROOT)}", file=sys.stderr)
    for v in cast.VOICES:
        print(f"  {v:<13}{c[v]:>5} speakers {w[v] / tot:>6.1%} of quoted words", file=sys.stderr)
    return path


def write_browse(out_dir: Path) -> Path:
    """The merged table (generated + config/cast.csv) to look at, e.g. output/cast.csv."""
    table = config.cast_table()
    editions = sorted({k[6:] for r in table.values() for k in r if k.startswith("label_")})
    rows = sorted(table.values(), key=lambda r: (-int(r.get("words") or 0), r["speaker_id"]))
    return config.write_cast(rows, editions, out_dir / "cast.csv")


