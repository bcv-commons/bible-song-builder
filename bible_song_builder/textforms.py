"""Forms of the Hebrew/Greek text itself (passage-facts v0.2), placed on the edition's tokens.

- ``fm.tx.refrain``: a line the text repeats in its chapter, each occurrence by its words.
- ``fm.tx.acrostic``: the alphabet letter of each verse or poetic line.
- ``fm.tx.halves``: a poetic verse (PSA, PRO, JOB) divided at its main accent into A and B.
- ``fm.ps.*``: psalm-heading terms, and selah.

Each fact names source words (MACULA keys); the alignment says which edition tokens render
them, so the marks hold for any aligned edition. Without an alignment there are no marks.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from functools import lru_cache

from . import fetch
from .align import Alignment

Tok = tuple[tuple[int, int], int]          # (edition chapter, verse), token index


@dataclass
class Marks:
    breaks: dict[tuple[int, int], set[int]] = field(default_factory=dict)        # extra line starts
    half_b: dict[tuple[int, int], int] = field(default_factory=dict)             # start of half B
    # lo, hi, "<fact id>#<occurrence>", how often the refrain occurs (a line covered by two
    # refrains takes the commoner)
    refrains: dict[tuple[int, int], list[tuple[int, int, str, int]]] = field(default_factory=dict)
    acrostic_runs: dict[Tok, str] = field(default_factory=dict)                 # a new letter starts here
    letters: list[tuple[Tok, str]] = field(default_factory=list)                # every unit's letter
    selah: dict[tuple[int, int], set[int]] = field(default_factory=dict)
    heading_terms: list[str] = field(default_factory=list)                     # fm.ps.* codes in the heading


@lru_cache(maxsize=1)
def codes() -> dict[str, str]:
    """code -> its English description (passage-facts codes.tsv)."""
    p = fetch.hf("passage-facts", "codes.tsv")
    with p.open(encoding="utf-8", newline="") as f:
        return {r[0]: r[2] for r in csv.reader(f, delimiter="\t") if len(r) > 2}


def _span(keys: list[str], first: str, last: str, al: Alignment) -> dict[tuple[int, int], set[int]]:
    out: dict[tuple[int, int], set[int]] = {}
    for k in keys:
        if first <= k <= last:
            hit = al.positions(k)
            if hit:
                out.setdefault(hit[0], set()).update(hit[1])
    return out


def _start(keys: list[str], first: str, last: str, al: Alignment) -> Tok | None:
    """The first edition token of a span (in the verse of its first rendered word)."""
    sp = _span(keys, first, last, al)
    if not sp:
        return None
    cv = min(sp)
    return cv, min(sp[cv])


def chapter_marks(facts: list[dict], rows: list[dict], al: Alignment, chapter: int, layout: dict) -> Marks:
    m = Marks()
    if al.kind == "none" or chapter in al.chapters_off:
        return m
    keys = sorted({k for r in rows for k in r["words"]})
    if not keys:
        return m
    lo_key, hi_key = keys[0], keys[-1]
    min_words = layout.get("chorus", {}).get("min_words", 3)
    use_refrains = layout.get("chorus", {}).get("source", "text") in ("text", "both")
    min_run = layout.get("stanzas", {}).get("acrostic_min_run", 2)

    def here(cv: tuple[int, int]) -> bool:
        return cv[0] == chapter

    for f in facts:
        if f.get("kind") != "form" or f["last"] < lo_key or f["first"] > hi_key:
            continue
        v = f.get("value", "")
        if v == "fm.tx.refrain" and use_refrains and f.get("words", 0) >= min_words:
            occ = f.get("occurrences", [])
            for n_occ, (a, b) in enumerate(occ, start=1):
                # a refrain may run over a verse end; each verse's piece must be long enough by itself
                per_verse: dict[tuple[int, int], list[str]] = {}
                for k in keys:
                    if a <= k <= b:
                        per_verse.setdefault((int(k[2:5]), int(k[5:8])), []).append(k)
                for ks in per_verse.values():
                    if len({k[:11] for k in ks}) < min_words:      # words, not morphemes (Hebrew key digit 12)
                        continue
                    for cv, pos in _span(ks, ks[0], ks[-1], al).items():
                        if here(cv) and pos:
                            lo, hi = min(pos), max(pos)
                            m.refrains.setdefault(cv, []).append((lo, hi, f"{f['id']}#{n_occ}", len(occ)))
                            m.breaks.setdefault(cv, set()).update({lo, hi + 1})
        elif v == "fm.tx.halves":
            halves = f.get("halves") or []
            if len(halves) == 2:
                s = _start(keys, halves[1][0], halves[1][1], al)
                if s and here(s[0]):
                    m.half_b[s[0]] = s[1]
        elif v == "fm.tx.acrostic":
            units = f.get("letters") or []
            # runs of the same letter (a unit with no letter belongs to the run before it)
            runs: list[tuple[str, list]] = []
            for a, b, letter in units:
                if letter and (not runs or runs[-1][0] != letter):
                    runs.append((letter, []))
                if runs:
                    runs[-1][1].append((a, b))
            stanzaic = runs and max(len(u) for _, u in runs) >= min_run
            for letter, us in runs:
                s = _start(keys, us[0][0], us[0][1], al)
                if s and here(s[0]):
                    m.letters.append((s, letter))
                    if stanzaic:
                        m.acrostic_runs[s] = letter
                        m.breaks.setdefault(s[0], set()).add(s[1])
        elif v == "fm.ps.selah":
            for cv, pos in _span(keys, f["first"], f["last"], al).items():
                if here(cv):
                    m.selah.setdefault(cv, set()).update(pos)
        elif v.startswith("fm.ps.") and v not in ("fm.ps.higgayon", "fm.ps.halleluyah"):
            s = _start(keys, f["first"], f["last"], al)
            # heading terms: on the first verse (or the title, which the verse map puts at verse 1)
            if (s and here(s[0]) and s[0][1] <= 1) or (s is None and int(f["first"][2:5]) == chapter):
                if v not in m.heading_terms:
                    m.heading_terms.append(v)
    return m
