"""Structure and setting inputs: clause lines (Hebrew or Greek) and passage facts."""
from __future__ import annotations

import json
from functools import lru_cache

import pyarrow.parquet as pq

from . import fetch

NT_BOOKS = {
    "MAT", "MRK", "LUK", "JHN", "ACT", "ROM", "1CO", "2CO", "GAL", "EPH", "PHP", "COL", "1TH", "2TH",
    "1TI", "2TI", "TIT", "PHM", "HEB", "JAS", "1PE", "2PE", "1JN", "2JN", "3JN", "JUD", "REV",
}

SONG_FORMS = {"fm.ms.song"}
SONG_QUOTES = {"qt.song", "qt.song_speech"}
POETIC_FORMS = {"fm.ms.lines", "fm.ed.lines", "fm.ed.qlines", "fm.ed.block", "fm.tr.poetry"}


def lines_dataset(book: str) -> str:
    return "greek-nt-clause-lines" if book in NT_BOOKS else "hebrew-clause-lines"


def clause_lines(book: str, chapters: set[int]) -> list[dict]:
    """Rows of ``data/lines-<BOOK>.parquet`` for the given spine chapters, in text order."""
    path = fetch.hf(lines_dataset(book), f"data/lines-{book}.parquet")
    rows = pq.read_table(path, filters=[("chapter", "in", sorted(chapters))]).to_pylist()
    rows.sort(key=lambda r: (r["chapter"], r["verse"], r["seg"], r.get("line") or 1))
    return rows


def passage_facts(book: str) -> list[dict]:
    p = fetch.hf("passage-facts", f"data/{book}.jsonl")
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def macula_book(book: str) -> str:
    """The two-digit MACULA book number of a USFM book code (GEN 01 … MAL 39, MAT 40 … REV 66)."""
    from .edition import BOOKS
    return f"{BOOKS.index(book) + 1:02d}"


@lru_cache(maxsize=1)
def _model_moods() -> list[dict]:
    return pq.read_table(fetch.hf("passage-moods-model", "data/moods.parquet")).to_pylist()


def model_moods(book: str) -> list[dict]:
    """passage-moods-model rows of a book: a passage, and the feeling families a model read in its
    words (strongest first). Model output, no human check."""
    return [r for r in _model_moods() if r["book"] == book]


COMMENTARY_DATASETS = ("hebrew-commentary-terms", "hebrew-commentary-terms-model")


@lru_cache(maxsize=2)
def _statements(dataset: str) -> list[dict]:
    t = pq.read_table(fetch.hf(dataset, "data/statements.parquet"))
    return [dict(r, dataset=dataset) for r in t.to_pylist()]


def commentary_statements(book: str, says: str | None = None) -> list[dict]:
    """The classical commentators' statements on a book (by rule, and read by a model), each with
    the ``dataset`` it comes from."""
    b = macula_book(book)
    return [r for ds in COMMENTARY_DATASETS for r in _statements(ds)
            if r["subject_first"][:2] == b and (says is None or r["says"] == says)]


def key_cv(key: str) -> tuple[int, int]:
    """Spine (chapter, verse) of a MACULA key (Hebrew 12 digits, Greek 11: BBCCCVVV...)."""
    return int(key[2:5]), int(key[5:8])


def fact_verses(fact: dict, all_verses: list[tuple[int, int]]) -> list[tuple[int, int]]:
    a, b = key_cv(fact["first"]), key_cv(fact["last"])
    return [cv for cv in all_verses if a <= cv <= b]


def setting_verses(facts: list[dict], spine_verses: list[tuple[int, int]],
                   cfg: dict | None = None) -> dict[str, set[tuple[int, int]]]:
    """Spine verses set as song and as poetic lines, by passage facts (codes: layout.toml [setting])."""
    cfg = cfg or {}
    song_forms = set(cfg.get("song_forms", SONG_FORMS))
    song_quotes = set(cfg.get("song_quotes", SONG_QUOTES))
    poetic_forms = set(cfg.get("poetic_forms", POETIC_FORMS))
    song: set[tuple[int, int]] = set()
    poetic: set[tuple[int, int]] = set()
    for f in facts:
        v = f.get("value")
        if f.get("layout") == "list":      # song layout for a list (JOS 12, EST 9), not a song
            continue
        if (f["kind"] == "form" and v in song_forms) or (f["kind"] == "quote" and v in song_quotes):
            song.update(fact_verses(f, spine_verses))
        elif f["kind"] == "form" and v in poetic_forms:
            poetic.update(fact_verses(f, spine_verses))
    return {"song": song, "poetic": poetic}


CLAUSE_SIGNAL_DATASETS = ("clause-connectives", "clause-columns")


@lru_cache(maxsize=2)
def _signals(testament: str) -> dict[str, dict]:
    """clause key -> link (clause-connectives), line and part_switch (clause-columns)."""
    f = "greek-nt" if testament == "nt" else "hebrew"
    out: dict[str, dict] = {}
    t = pq.read_table(fetch.hf("clause-connectives", f"data/{f}.parquet"), columns=["clause_key", "link"])
    for r in t.to_pylist():
        out[r["clause_key"]] = {"link": r["link"]}
    t = pq.read_table(fetch.hf("clause-columns", f"data/{f}.parquet"),
                      columns=["clause_key", "line", "part_switch", "strong", "conj", "actor"])
    for r in t.to_pylist():
        sig = out.setdefault(r["clause_key"], {})
        sig.update(line=r["line"], part_switch=r["part_switch"])
        # Greek καὶ ἐγένετο (γίνομαι, aorist indicative) opening a scene: the counterpart of Hebrew
        # וַיְהִי, which clause-connectives already gives as link "episode"
        if (testament == "nt" and str(r["strong"]).lstrip("G0") == "1096" and r["conj"] == "aorist_indicative"
                and r["line"] in ("main", "setting")):
            sig["link"] = "episode"
        # Hebrew וַיְהִי / וְהָיָה with no actor of its own ("And it came to pass after these things"):
        # clause-connectives gives "episode" only to some of them
        if (testament == "ot" and str(r["strong"]).lstrip("H0") == "1961" and r["conj"] in ("wayyiqtol", "weqatal")
                and r["actor"] == "none"):
            sig["link"] = "episode"
    return out


def clause_key(row: dict) -> str | None:
    """The key clause-connectives and clause-columns use: Hebrew clause_key, Greek the segment's first word."""
    return row.get("clause_key") or row.get("first")


def clause_signals(book: str) -> dict[str, dict]:
    return _signals("nt" if book in NT_BOOKS else "ot")
