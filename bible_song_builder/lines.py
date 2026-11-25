"""Lyric lines, voices and stanzas for one chapter.

Line breaks. Each clause line breaks the edition's verse at the EARLIEST target token any
of its words aligned to. That is our reading of "the target token aligned to the first
aligned word": in target order, not source order. Source order breaks badly because a
Hebrew line usually opens with a conjunction prefix (וַ) that BSB renders late or not at
all, and BSB reorders clauses (Ruth 1:6). The breaks of a verse are sorted, so a clause that
BSB moves ahead still gets its own line. A clause line with no aligned word adds no break;
it stays with the line before. A verse always starts a line. Without an alignment, one
verse is one line.

Stanzas. A new stanza starts after the line holding the last word of a clause line with
``para_end`` (Leningrad) or ``para_end_mam``, and at a new acrostic letter. A run longer than
``max_lines`` is split at verse starts by source signals (``break_strength``): a new episode,
"and now", a setting, a new participant, a change between narrator and speaker. The edition's
own headings and paragraphs count only if layout.toml / editions.toml give them weight.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field, replace
from functools import lru_cache

from . import cast, config, fetch, structure
from .align import Alignment
from .edition import BookText, Verse
from .textforms import Marks

OPENING = set("“‘\"'([{«‹¿¡—–-")    # default; layout.toml [text] line_start_punctuation


def count_units(text: str, mode: str = "words") -> int:
    """Length of a text in words, or in letters for scripts without spaces (layout.toml [text] count)."""
    if mode == "characters":
        return len(re.findall(r"[^\W\d_]", text))
    return len(re.findall(r"[^\W\d_]+", text))


@dataclass
class Speaker:
    id: str | None
    label: str | None          # the edition's own words for the speaker's name (notes file only)
    voice: str                 # voice class from config/cast.csv
    pointer: dict | None = None   # where the chapter has no words for the speaker: their main naming place (speaker_hits)


@dataclass
class LyricLine:
    cv: tuple[int, int]        # edition chapter, verse
    text: str
    first_token: int
    quote: str | None          # quotation id; None = narrator / the text's own voice
    speaker: Speaker | None
    row_seg: int | None        # clause segment that started this line (for tracing)
    para_end: bool = False     # a paragraph of the source ends in this line
    refrain: str | None = None   # (part of) a refrain the text repeats: "<passage-facts id>#<occurrence>"
    acrostic: str | None = None  # a new acrostic letter starts on this line
    selah: bool = False          # holds the word selah (fm.ps.selah)
    clause: str | None = None    # key of the clause that starts the line (clause-connectives / -columns)
    opening: list[str] | None = None  # at a verse start: the verse's first clause in source order and
                                      # its first top-level clause (what break_strength reads)


@dataclass
class Stanza:
    lines: list[LyricLine] = field(default_factory=list)
    # why it starts: start, acrostic, para (source paragraph), paragraph (edition's, NT),
    # split (--max-lines), chorus (cut around a chorus line), midverse (such a cut inside a verse)
    reason: str = "start"

    @property
    def verses(self) -> list[tuple[int, int]]:
        return sorted({ln.cv for ln in self.lines})


def _row_targets(row: dict, al: Alignment) -> dict[tuple[int, int], set[int]]:
    out: dict[tuple[int, int], set[int]] = {}
    for k in row["words"]:
        hit = al.positions(k)
        if hit:
            out.setdefault(hit[0], set()).update(hit[1])
    return out


def _cut_start(text: str, start: int, opening: set[str] = OPENING) -> int:
    """Move a line start back over the opening punctuation that belongs to it."""
    while start > 0 and text[start - 1] in opening:
        start -= 1
    return start


def _slice(v: Verse, starts: list[int], opening: set[str] = OPENING) -> list[tuple[int, str]]:
    assert v.spans is not None
    chars = [_cut_start(v.text, v.spans[t][0], opening) for t in starts]
    chars[0] = 0
    out = []
    for i, t in enumerate(starts):
        end = chars[i + 1] if i + 1 < len(starts) else len(v.text)
        piece = v.text[chars[i]:end].strip()
        if piece:
            out.append((t, piece))
    return out


@lru_cache(maxsize=None)
def strip_endings(edition: str) -> tuple[str, ...]:
    """Endings cut off a speaker label ("Naomi’s" -> "Naomi"), from config/languages.toml."""
    iso = fetch.pins()["editions"][edition]["iso"]
    return tuple(config.language(iso).get("label_strip_endings", []))


@lru_cache(maxsize=None)
def edge_words(edition: str) -> set[str]:
    """Words trimmed off the ends of a speaker label: the aligned span of a name can carry its
    Hebrew word's conjunction or preposition ("But Naomi"). From config/languages.toml."""
    iso = fetch.pins()["editions"][edition]["iso"]
    return {w.lower() for w in config.language(iso).get("label_edge_words", [])}


def phrase(bt: BookText, cv: tuple[int, int], pos: set[int], max_tokens: int = 6) -> str | None:
    """The edition's words at these token positions of a verse (a name, a term), trimmed of the
    language's edge words and endings; None if too long."""
    v = bt.verses.get(cv)
    if not v or not v.spans or not pos:
        return None
    a, b = min(pos), max(pos)
    if b >= len(v.spans) or b - a + 1 > max_tokens:
        return None
    edge = edge_words(bt.edition)
    while a <= b and v.tokens[a].lower() in edge:
        a += 1
    while b >= a and v.tokens[b].lower() in edge:
        b -= 1
    if a > b:
        return None
    s = v.text[v.spans[a][0]:v.spans[b][1]]
    for ending in strip_endings(bt.edition):
        if s.endswith(ending):
            s = s[: -len(ending)]
            break
    s = s.strip(" ,;:.!?“”‘’\"")
    return s or None


def merge_short(lines: list[LyricLine], min_tokens: int, count: str = "words") -> list[LyricLine]:
    """Join a line of fewer than ``min_tokens`` words to the next line of the same verse and
    voice, else to the previous one. Only whole lines are joined; no text changes. A refrain
    line joins only refrain lines of the same refrain, and nothing joins across the start of
    an acrostic letter."""
    def n_tok(ln: LyricLine) -> int:
        return count_units(ln.text, count)

    def same(a: LyricLine, b: LyricLine) -> bool:     # may a and the following b be one line?
        return a.cv == b.cv and a.quote == b.quote and a.refrain == b.refrain and b.acrostic is None

    def join(a: LyricLine, b: LyricLine) -> LyricLine:
        return replace(a, text=f"{a.text} {b.text}", para_end=a.para_end or b.para_end,
                       selah=a.selah or b.selah)

    out = list(lines)
    i = 0
    while i < len(out):
        ln = out[i]
        if n_tok(ln) < min_tokens:
            if i + 1 < len(out) and same(ln, out[i + 1]):
                out[i + 1] = join(ln, out[i + 1])
                del out[i]
                continue
            if i > 0 and same(out[i - 1], ln):
                out[i - 1] = join(out[i - 1], ln)
                del out[i]
                i -= 1
                continue
        i += 1
    return out


def main_naming(ref: dict, prefix: str = "") -> tuple[str, int] | None:
    """The speaker's main naming place in the plan, the same for every edition: among the entries in
    this book (word keys starting with ``prefix``), the ``named`` one with the most clause rows (the
    earlier on a tie), else the main ``described`` one; else the main ``named`` one in another book
    (the Greek names a speaker where they are first named, also in another book); None if none."""
    for part, here in (("named", True), ("described", True), ("named", False)):
        entries = [(i, n) for i, (keys, n) in enumerate(ref.get(part) or []) if keys
                   and keys[0].startswith(prefix) == here]
        if entries:
            return part, max(entries, key=lambda e: (e[1], -e[0]))[0]
    return None


def speaker_hits(refs: dict[str, dict], al: Alignment, bt: BookText, book: str = "", to_ed=None,
                 lexemes: dict[int, list[str]] | None = None) -> dict[str, tuple]:
    """speaker_id -> (voice, hits, pointer): where the edition's text names each speaker, once per
    book. hits: (part, label, n, edition chapter, main) in plan order; part "named" (the speaker's
    name, ``speaker_name_ref``) or "described" (the words introducing them); main: at the speaker's
    main naming place (main_naming). pointer: that place, {book, verse (the edition's "c:v"), spine
    [c, v], keys (source word keys), strong (their Strong's numbers, for this book's keys)}, or
    None. ``refs``: the plan's speakers (cast.speaker_refs); the voice is the cast table's, else the
    plan's ``voice``; ``to_ed(book, (c, v))``: spine -> edition (c, v) or None; ``lexemes``:
    align.lexeme_keys of the book (for strong)."""
    from .edition import BOOKS
    prefix = f"{BOOKS.index(book) + 1:02d}" if book in BOOKS else ""
    to_ed = to_ed or (lambda b, cv: cv)
    strong_of = {k: f"{'G' if len(k) == 11 else 'H'}{n}" for n, keys in (lexemes or {}).items() for k in keys}
    out = {}
    for sid, ref in refs.items():
        main = main_naming(ref, prefix)
        hits = []
        for part in ("named", "described"):
            for i, (keys, n) in enumerate(ref.get(part, [])):
                per_verse: dict[tuple[int, int], set[int]] = {}
                for k in keys:
                    hit = al.positions(k)
                    if hit:
                        per_verse.setdefault(hit[0], set()).update(hit[1])
                for cv, pos in per_verse.items():
                    label = phrase(bt, cv, pos)
                    if label:
                        hits.append((part, label, n, cv[0], main == (part, i)))
        pointer = None
        if main:
            keys = ref[main[0]][main[1]][0]
            where = BOOKS[int(keys[0][:2]) - 1] if keys[0][:2].isdigit() and 0 < int(keys[0][:2]) <= len(BOOKS) else book
            spine = (int(keys[0][2:5]), int(keys[0][5:8]))
            ed = to_ed(where, spine)
            pointer = {"book": where, "verse": f"{ed[0]}:{ed[1]}" if ed else None, "spine": list(spine),
                       "keys": list(keys), "strong": list(dict.fromkeys(strong_of[k] for k in keys if k in strong_of))}
        out[sid] = (cast.voice_of(sid, None, ref.get("voice")), hits, pointer)
    return out


def speaker_labels(hits: dict, chapter: int | None = None) -> dict[str, Speaker]:
    """speaker_id -> Speaker for one edition chapter. The label is the commonest of the edition's
    words naming the speaker in this chapter (named, else described); where the chapter has none,
    the words at the speaker's main naming place, and ``pointer`` says where that is, so a client
    with only this chapter can fetch that chapter; else None (the cast table's name is used).
    Nothing depends on which other chapters the client has, except that the pointer's chapter must
    be among them for its words. ``chapter`` None: the commonest in the book (the cast table).
    ``hits``: speaker_hits()."""
    out = {}
    for sid, (voice, hs, pointer) in hits.items():
        def pick(keep) -> str | None:
            for part in ("named", "described"):
                c: Counter = Counter()
                for h in hs:
                    if h[0] == part and keep(h):
                        c[h[1]] += h[2]
                if c:
                    return c.most_common(1)[0][0]
            return None
        own = pick(lambda h: chapter is None or h[3] == chapter)
        label = own if own is not None or chapter is None else pick(lambda h: h[4])
        out[sid] = Speaker(sid, label, voice, pointer if own is None and chapter is not None else None)
    return out


def build_lines(bt: BookText, chapter: int, rows: list[dict], al: Alignment,
                speakers: dict[str, Speaker], vmap_cv, min_tokens: int = 3,
                marks: Marks | None = None, poetry: str = "clauses+halves",
                text_cfg: dict | None = None, pull: bool = False) -> list[LyricLine]:
    """Lyric lines of an edition chapter; ``para_end`` is set on a line in which a
    ``para_end`` clause line ends.

    ``marks`` (textforms) add line starts: each refrain occurrence is its own line, an acrostic
    letter starts a line, and a poetic verse breaks where its half B starts. ``poetry`` says
    whether such a verse also breaks at its clauses ("clauses+halves"), only at the halves
    ("halves"), or only at the clauses ("clauses").

    ``pull``: a clause's line start moves back over the unaligned words just before it ("when the |
    judges ruled" -> "| when the judges ruled"), up to punctuation, an aligned word or the line
    before. For alignments of content words only (compact), where function words have no link."""
    marks = marks or Marks()
    text_cfg = text_cfg or {}
    opening = set(text_cfg.get("line_start_punctuation", "")) or OPENING
    verses = bt.chapter_verses(chapter)
    # break candidates per edition verse: token -> the first clause row (source order) breaking there
    breaks: dict[tuple[int, int], dict[int, dict]] = {}
    owner: dict[tuple[int, int], dict[int, dict]] = {}
    para_ends: list[tuple[tuple[int, int], int]] = []
    verse_rows: dict[tuple[int, int], list[dict]] = {}
    for r in rows:
        targets = _row_targets(r, al) if al.kind != "none" else {}
        if not targets:
            cv = vmap_cv((r["chapter"], r["verse"]))
            if cv:
                verse_rows.setdefault(cv, []).append(r)
        for cv, pos in targets.items():
            breaks.setdefault(cv, {}).setdefault(min(pos), r)
            for p in pos:
                owner.setdefault(cv, {}).setdefault(p, r)
            verse_rows.setdefault(cv, []).append(r)
        if r.get("para_end") or r.get("para_end_mam"):
            if targets:
                cv = max(targets)
                para_ends.append((cv, max(targets[cv])))
            else:
                cv = vmap_cv((r["chapter"], r["verse"]))
                if cv:
                    para_ends.append((cv, 10 ** 9))

    # a quote inside a speech (Hebrew ids "q00016.t1" inside "q00016") is sung by the outer
    # speaker unless cast-rules.toml says nested_quotes = "inner"
    outer = config.cast_rules().get("nested_quotes", "outer") == "outer"
    top_speaker = {r["quotation"]: cast.speaker_id(r) for r in rows
                   if r.get("quotation") and "." not in r["quotation"]}

    def voice(r: dict | None) -> tuple[str | None, Speaker | None]:
        if not r or not r.get("quotation"):
            return None, None
        q, sid = r["quotation"], cast.speaker_id(r)
        if outer and "." in q and q.split(".")[0] in top_speaker:
            q = q.split(".")[0]
            sid = top_speaker[q]
        return q, (speakers.get(sid) if sid else None) or Speaker(sid, None, cast.voice_of(sid, None))

    lines: list[LyricLine] = []
    for v in verses:
        cv = (v.chapter, v.verse)
        cand = breaks.get(cv, {})
        if al.kind == "none" or v.spans is None or not cand:
            # one line per verse; its voice is the voice of most of the verse's clause lines
            vr = verse_rows.get(cv, [])
            by_words = Counter()
            for r in vr:
                by_words[r.get("quotation")] += len(r["words"])
            q = by_words.most_common(1)[0][0] if by_words else None
            r0 = next((r for r in vr if r.get("quotation") == q), None)
            qq, sp = voice(r0)
            lines.append(LyricLine(cv, v.text, 0, qq, sp, r0["seg"] if r0 else None))
        else:
            base = set(cand)
            hb = marks.half_b.get(cv)
            if hb is not None and poetry != "clauses":
                base = ({hb} if poetry == "halves" else base | {hb})
            base |= marks.breaks.get(cv, set())
            starts = sorted({0, *(t for t in base if t < len(v.tokens))})
            moved: dict[int, int] = {}
            if pull:
                own = owner.get(cv, {})
                fixed = marks.breaks.get(cv, set()) | ({hb} if hb is not None else set())
                new: list[int] = []
                for t in starts:
                    s = t
                    if t in cand and t not in fixed:
                        lo = new[-1] if new else -1
                        while (s - 1 > lo and s - 1 not in own
                               and not v.text[v.spans[s - 1][1]:v.spans[s][0]].strip()):
                            s -= 1
                    new.append(s)
                    moved[s] = t
                starts = new
            prev_row = None
            first = len(lines)
            for t, piece in _slice(v, starts, opening):
                r = cand.get(moved.get(t, t)) or owner.get(cv, {}).get(t) or prev_row
                prev_row = r
                qq, sp = voice(r)
                lines.append(LyricLine(cv, piece, t, qq, sp, r["seg"] if r else None,
                                       clause=structure.clause_key(r) if r else None))
            _mark(lines[first:], cv, len(v.tokens), marks)
        _opening(lines, cv, verse_rows.get(cv, []))
        for pcv, ptok in para_ends:
            if pcv == cv:
                idx = max((i for i, ln in enumerate(lines) if ln.cv == cv and ln.first_token <= ptok),
                          default=len(lines) - 1)
                lines[idx].para_end = True
    return merge_short(lines, min_tokens, text_cfg.get("count", "words"))


def _opening(lines: list[LyricLine], cv: tuple[int, int], vrows: list[dict]) -> None:
    """Give the verse's first line the keys of the clauses that open the verse in the source."""
    first = next((ln for ln in lines if ln.cv == cv), None)
    if first is None or not vrows:
        return
    rows = sorted(vrows, key=lambda r: (r["chapter"], r["verse"], r["seg"], r.get("line") or 1))
    keys = [structure.clause_key(rows[0])]
    top = next((r for r in rows if not r.get("depth")), None)
    if top is not None:
        keys.append(structure.clause_key(top))
    first.opening = [k for k in dict.fromkeys(keys) if k]


def _mark(vlines: list[LyricLine], cv: tuple[int, int], n_tokens: int, marks: Marks) -> None:
    """Flag the lines of one verse: refrain, acrostic letter start, selah."""
    for k, ln in enumerate(vlines):
        end = (vlines[k + 1].first_token if k + 1 < len(vlines) else n_tokens) - 1
        best = -1
        for lo, hi, rid, n in marks.refrains.get(cv, []):
            if lo <= ln.first_token and end <= hi and n > best:
                ln.refrain, best = rid, n
        for (mcv, tok), letter in marks.acrostic_runs.items():
            if mcv == cv and ln.first_token == tok:
                ln.acrostic = letter
        if any(ln.first_token <= t <= end for t in marks.selah.get(cv, ())):
            ln.selah = True


# How strongly the source marks a new start at a verse, read from the clause that opens it
# (bcv-commons clause-connectives `link`, clause-columns `line` and `part_switch`).
SOURCE_BREAK = {
    "link": {"episode": 3, "and_now": 1, "development": 1, "time": 1},
    "line": {"setting": 1},
    "part_switch": {"switch": 1},
}
VOICE_CHANGE = 1          # the narrator takes over from a speaker, or the other way round
STANZA_COST = 2           # what one more stanza costs when a long run is split (vs. the strengths above)


def break_strength(ln: LyricLine, prev: LyricLine, signals: dict[str, dict], bt: BookText,
                   edition_weights: dict | None = None) -> int:
    """Source signals for a stanza start before ``ln``; the edition's own headings and
    paragraphs count only by the weights set in config (layout.toml [stanzas])."""
    score = 0
    for field_, table in SOURCE_BREAK.items():
        vals = [signals.get(k, {}).get(field_) for k in (ln.opening or [ln.clause]) if k]
        if field_ == "part_switch":       # a new participant counts in narration, not inside speech
            vals = [v for k, v in zip(ln.opening or [ln.clause], vals)
                    if signals.get(k or "", {}).get("line") != "speech"]
        score += max((table.get(v, 0) for v in vals), default=0)
    if (ln.quote is None) != (prev.quote is None):
        score += VOICE_CHANGE
    w = edition_weights or {}
    if ln.cv in bt.heading_before:
        score += w.get("edition_heading_weight", 0)
    if ln.cv in bt.paragraph_starts:
        score += w.get("edition_paragraph_weight", 0)
    return score


def stanzas(lines: list[LyricLine], bt: BookText, max_lines: int, signals: dict[str, dict] | None = None,
            cfg: dict | None = None, is_nt: bool = False) -> list[Stanza]:
    """Stanzas: a new one after a source paragraph end and at a new acrostic letter (and at the
    edition's paragraphs if layout.toml asks for it). A run longer than ``max_lines`` is split at
    verse starts: into as few stanzas as fit, at the strongest source breaks, as even as possible."""
    cfg = cfg or {}
    signals = signals or {}
    reason: dict[int, str] = {}
    for i, ln in enumerate(lines):
        if ln.para_end:
            reason.setdefault(i + 1, "para")
    starts_verse = [i for i, ln in enumerate(lines) if i == 0 or ln.cv != lines[i - 1].cv]
    ed_par = cfg.get("edition_paragraphs", "never")
    if ed_par == "always" or (ed_par == "nt" and is_nt):
        for i in starts_verse:
            if lines[i].cv in bt.paragraph_starts:
                reason.setdefault(i, "paragraph")
    for i, ln in enumerate(lines):
        if ln.acrostic:
            reason[i] = "acrostic"
    cuts = sorted(c for c in reason if 0 < c < len(lines))
    bounds = [0, *cuts, len(lines)]
    chunks = [(a, b) for a, b in zip(bounds, bounds[1:]) if b > a]
    strength = {i: break_strength(lines[i], lines[i - 1], signals, bt, cfg) for i in starts_verse if i}
    min_lines = cfg.get("min_lines", 2)
    stanza_cost = STANZA_COST

    def split(a: int, b: int) -> list[tuple[int, int]]:
        if b - a <= max_lines:
            return [(a, b)]
        cand = [i for i in starts_verse if a + min_lines <= i <= b - min_lines]
        pts = [a, *cand, b]
        # best[j] for pts[j]: (cost, largest piece), back pointer. Each stanza costs
        # `stanza_cost`; each split earns its source strength (so a strong break may buy an extra stanza)
        best: list[tuple | None] = [None] * len(pts)
        back = [0] * len(pts)
        best[0] = (0, 0)
        for j in range(1, len(pts)):
            for i in range(j):
                size = pts[j] - pts[i]
                if size > max_lines or best[i] is None:
                    continue
                cost, mx = best[i]
                c = (cost + stanza_cost - (strength.get(pts[i], 0) if i else 0), max(mx, size))
                if best[j] is None or c < best[j]:
                    best[j], back[j] = c, i
        if best[-1] is None:            # no verse start to cut at: leave it whole
            return [(a, b)]
        out, j = [], len(pts) - 1
        while j:
            out.append((pts[back[j]], pts[j]))
            j = back[j]
        return out[::-1]

    out = []
    for a, b in chunks:
        for x, y in split(a, b):
            out.append(Stanza(lines[x:y], reason.get(x, "split") if x else "start"))
    return out
