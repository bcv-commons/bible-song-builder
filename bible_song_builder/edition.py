"""The lyric-language text: one edition, verse by verse, read the shared bcv-commons way.

Text comes from the edition's pinned USJ release (for the BSB: BSB-publishing/bsb2usfm) and is
extracted with the vendored ``tools/verse-text`` package, so the verse text, its tokens and the
book fingerprint are those the alignments were built on (checked by the fingerprints).
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vendor" / "verse_text"))

from bcv_tokenize import file_hash, fingerprints, strip_marks, tokenize  # noqa: E402
from verse_text import extract_usj, first_number  # noqa: E402

from . import config, fetch  # noqa: E402

PARAGRAPH_MARKERS = {"p", "m", "pmo", "pm", "pi", "pi1", "pi2", "nb", "po", "pr", "mi"}
POETRY_PREFIX = "q"


@dataclass
class Verse:
    chapter: int
    verse: int
    text: str
    tokens: list[str]
    spans: list[tuple[int, int]] | None  # char offsets of each token in ``text``; None if not reproducible


@dataclass
class BookText:
    edition: str
    book: str
    verses: dict[tuple[int, int], Verse]
    fingerprint: str
    chapter_fingerprints: dict[int, str]
    paragraph_starts: set[tuple[int, int]] = field(default_factory=set)  # a prose paragraph opens at this verse
    heading_before: set[tuple[int, int]] = field(default_factory=set)    # a section heading stands before this verse
    poetry_verses: set[tuple[int, int]] = field(default_factory=set)     # the edition sets the verse in poetic lines
    name: str = ""                                                        # the book's short name (\\toc2)
    titles: dict[tuple[int, int], str] = field(default_factory=dict)       # superscription before this verse

    @property
    def file_hash(self) -> str:
        return file_hash(self.fingerprint)

    def chapter_verses(self, chapter: int) -> list[Verse]:
        return [v for (c, _), v in sorted(self.verses.items()) if c == chapter]


def token_spans(text: str) -> list[tuple[int, int]] | None:
    """Character offsets of the tokens ``tokenize(text)`` gives, or None where the
    per-character reading cannot reproduce them (scripts with context-dependent rules)."""
    spans: list[tuple[int, int]] = []
    start = None
    for i, ch in enumerate(text):
        s = strip_marks(ch)
        is_word = bool(s) and all(unicodedata.category(c)[0] in ("L", "M") for c in s)
        if is_word and start is None:
            start = i
        elif not is_word and start is not None and s != "":
            spans.append((start, i))
            start = None
    if start is not None:
        spans.append((start, len(text)))
    if [strip_marks(text[a:b]) for a, b in spans] != tokenize(text):
        return None
    return spans


def _walk_layout(usj: dict, book: BookText) -> None:
    """Paragraph starts, headings and poetic verses from the USJ's paragraph markers."""
    chapter = 0
    last_verse: tuple[int, int] | None = None
    pending_heading = False
    for node in usj["content"]:
        if node.get("type") == "chapter":
            chapter = int(node["number"])
            continue
        if node.get("type") != "para":
            continue
        marker = node.get("marker", "")
        content = node.get("content", []) or []
        if marker.startswith("s") or marker in ("ms", "mr", "d"):
            pending_heading = True
            continue
        opens_with_verse = bool(content) and isinstance(content[0], dict) and content[0].get("type") == "verse"
        verse_nums = [int(first_number(x["number"])) for x in content
                      if isinstance(x, dict) and x.get("type") == "verse"]
        if opens_with_verse:
            here = (chapter, verse_nums[0])
            if marker in PARAGRAPH_MARKERS:
                book.paragraph_starts.add(here)
            if pending_heading:
                book.heading_before.add(here)
        if marker.startswith(POETRY_PREFIX):
            for v in ([last_verse] if last_verse and not opens_with_verse else []) + [(chapter, n) for n in verse_nums]:
                book.poetry_verses.add(v)
        if verse_nums:
            last_verse = (chapter, verse_nums[-1])
            pending_heading = False


BOOKS = ("GEN EXO LEV NUM DEU JOS JDG RUT 1SA 2SA 1KI 2KI 1CH 2CH EZR NEH EST JOB PSA PRO ECC SNG ISA JER "
         "LAM EZK DAN HOS JOL AMO OBA JON MIC NAM HAB ZEP HAG ZEC MAL MAT MRK LUK JHN ACT ROM 1CO 2CO GAL EPH "
         "PHP COL 1TH 2TH 1TI 2TI TIT PHM HEB JAS 1PE 2PE 1JN 2JN 3JN JUD REV").split()


def books(edition: str) -> list[str]:
    """The edition's books, in canonical order (those its release has a USJ file for)."""
    d = fetch.release_dir(fetch.pins()["editions"][edition]["text"])
    have = {p.stem for p in d.glob("*.usj")}
    return [b for b in BOOKS if b in have]


def _is(n, kind: str) -> bool:
    return isinstance(n, dict) and n.get("type") == kind


def lift_titles(usj: dict) -> dict[tuple[int, int], str]:
    """A psalm title is a ``\\d`` paragraph that holds the verse-1 marker (``\\d \\v 1 A Psalm of
    David``). The aligned text has the title outside verse 1, so the title's text stays in the
    ``d`` paragraph (a heading, not sung) and the verse marker moves to the next paragraph with
    content. Returns {(chapter, verse): title}."""
    titles: dict[tuple[int, int], str] = {}
    cont = usj["content"]
    chapter = 0
    for i, p in enumerate(cont):
        if _is(p, "chapter"):
            chapter = int(p["number"])
        if not (_is(p, "para") and p.get("marker") == "d"):
            continue
        vs = [x for x in p.get("content") or [] if _is(x, "verse")]
        if not vs:
            continue
        title = " ".join(_usj_text(x) if isinstance(x, dict) else x for x in p["content"] if not _is(x, "verse")
                         and not _is(x, "note")).split()
        p["content"] = [x for x in p["content"] if not _is(x, "verse")]
        for q in cont[i + 1:]:
            if _is(q, "para") and q.get("content"):
                q["content"] = vs + [" "] + q["content"]
                break
        titles[(chapter, int(first_number(vs[0]["number"])))] = " ".join(title)
    return titles


def restore_note_spaces(n) -> int:
    """The bsb2usfm USJ export (v5.20) drops the space between a footnote (or a char span) and a
    following char span: USFM ``punishment\\f …\\f* \\add is\\add*`` becomes "punishmentis".
    Put the space back. Returns how many were restored."""
    if not isinstance(n, dict) or not isinstance(n.get("content"), list) or n.get("type") == "note":
        return 0
    out: list = []
    k = 0
    for x in n["content"]:
        if out and _is(x, "char") and isinstance(out[-1], dict) and out[-1].get("type") in ("note", "char"):
            out.append(" ")
            k += 1
        out.append(x)
    n["content"] = out
    return k + sum(restore_note_spaces(x) for x in out)


def trim_span_spaces(n) -> int:
    """The BSB USFM has a space inside some \\add spans before punctuation (``\\add his role \\add*.``,
    187 places), which reads as "role ." Drop that space when the text after the span starts with
    punctuation. Returns how many were trimmed."""
    if not isinstance(n, dict) or not isinstance(n.get("content"), list):
        return 0
    k = 0
    c = n["content"]
    for i, x in enumerate(c):
        nxt = c[i + 1] if i + 1 < len(c) else None
        if (_is(x, "char") and isinstance(nxt, str) and nxt[:1] and not nxt[0].isalnum() and not nxt[0].isspace()
                and x.get("content") and isinstance(x["content"][-1], str) and x["content"][-1].endswith(" ")):
            x["content"][-1] = x["content"][-1].rstrip()
            k += 1
    return k + sum(trim_span_spaces(x) for x in c)


def _usj_text(n) -> str:
    if isinstance(n, str):
        return n
    return "".join(_usj_text(c) for c in n.get("content", []) or [])


def book_name(usj: dict, book: str) -> str:
    """The book's short name, from ``\\toc2`` (or ``\\h``)."""
    found = {p.get("marker"): _usj_text(p).strip() for p in usj["content"] if _is(p, "para")
             and p.get("marker") in ("toc2", "h")}
    return found.get("toc2") or found.get("h") or book


FIXES = ("titles-in-d", "note-spaces", "span-spaces")


def load_book(edition: str, book: str) -> BookText:
    """The edition's text of a book, from its pinned USJ release (pins.json "releases"), with the
    repairs editions.toml lists for the edition."""
    ed = fetch.pins()["editions"][edition]
    ecfg = config.edition(edition)
    fixes = ecfg.get("fixes", [])
    unknown = [f for f in fixes if f not in FIXES]
    if unknown:
        raise config.ConfigError(f"config/editions.toml [{edition}]: unknown fix(es) {', '.join(unknown)}; "
                                 f"known: {', '.join(FIXES)}")
    path = fetch.release_dir(ed["text"]) / f"{book}.usj"
    if not path.exists():
        raise config.ConfigError(f"{edition} has no book {book} (no {path.name} in release {ed['text']})")
    usj = json.loads(path.read_text(encoding="utf-8"))
    titles: dict[tuple[int, int], str] = {}
    if "note-spaces" in fixes:
        restore_note_spaces(usj)
    if "span-spaces" in fixes:
        trim_span_spaces(usj)
    if "titles-in-d" in fixes and book in ecfg.get("title_books", []):
        titles = lift_titles(usj)
    verses: dict[tuple[int, int], Verse] = {}
    for ch, vs in extract_usj(usj).items():
        for v in vs:
            key = (int(ch), int(v["verse"]))
            verses[key] = Verse(key[0], key[1], v["text"], tokenize(v["text"]), token_spans(v["text"]))
    fp, ch_fps = fingerprints({k: v.text for k, v in verses.items()})
    bt = BookText(edition, book, verses, fp, ch_fps, name=book_name(usj, book), titles=titles)
    _walk_layout(usj, bt)
    return bt
