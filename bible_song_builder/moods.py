"""Chapter moods: where the Hebrew/Greek itself gives a reason for a chapter's own style.

A book keeps one style (its profile). A chapter gets its own style only where the source says
something about how it sounds:

- ``heading``   a psalm-heading term naming the kind of piece (תְּפִלָּה a prayer, תְּהִלָּה praise,
                לְתוֹדָה thanksgiving, שִׁיר יְדִידֹת a love song, the sabbath, שִׁיר הַמַּעֲלוֹת a song of
                ascents) or הַלְלוּ יָהּ in the text;
                and the instruments the heading names (בִּנְגִינוֹת strings, הַנְּחִילוֹת flutes)
- ``song``      a song in narrative: the Masoretic song layout covers the chapter, in a book that
                is not itself song (EXO 15, DEU 32, JDG 5, 2SA 22, 1CH 16)
- ``type``      the psalm's type as the Tyndale Open Study Notes name it (passage-facts ``fm.gn.*``),
                named by its Hebrew term (qinah, tehillah, todah, mivtach …)
- ``purpose``   the psalm's purpose as Scriptura states it (``fm.pu.*``), the same Hebrew terms
- ``delivery``  most of the chapter is speech delivered one way (passage-facts ``delivery``):
                a lament (EZK 19), a prayer (NEH 9), a rebuke (MAT 23)

Where cues give different moods, the cue first in moods.toml ``sources`` wins (a heading's own
word before a scholar's reading), then the mood first in ``priority``.

Which cue gives which mood is in config/moods.toml; the words the mood adds to the style line
are in config/profiles.toml ([moods], [instruments]). Facts are in source chapters; the chapter
of the edition is found through the verse map.
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from dataclasses import dataclass

from . import structure, textforms
from .config import ConfigError, toml
from .config import book as config_book

# Heading terms of the text that name a kind of piece, and the mood they give.
HEADING_MOODS = {
    "fm.ps.tefillah": "prayer",
    "fm.ps.tehillah": "praise",
    "fm.ps.halleluyah": "praise",
    "fm.ps.letodah": "thanksgiving",
    "fm.ps.yedidot": "love_song",
    "fm.ps.shabbat": "sabbath",
    "fm.ps.maalot": "pilgrimage",       # שִׁיר הַמַּעֲלוֹת a song of ascents, sung going up to Jerusalem
}
HEADING_INSTRUMENTS = {"fm.ps.neginot": "strings", "fm.ps.nechilot": "flutes"}


@dataclass
class Mood:
    mood: str | None                 # e.g. "lament"; None = only an instrument
    basis: str                       # heading, song, delivery
    evidence: str                    # what in the source gave it
    instruments: tuple[str, ...] = ()
    style: str | None = None         # a whole style line set by hand (books/<BOOK>.toml)
    share: float = 1.0               # how much of the chapter the cue covers


def _verses(ref: str) -> list[tuple[int, int]]:
    """The verses of a passage-facts ref ("LUK 1:68-73", "PSA 3:1", "GEN 1:31-2:3")."""
    m = re.match(r"\S+ (\d+):(\d+)(?:-(?:(\d+):)?(\d+))?", ref)
    if not m:
        return []
    c, a = int(m[1]), int(m[2])
    c2 = int(m[3]) if m[3] else c
    b = int(m[4]) if m[4] else a
    if c2 != c:
        return [(c, v) for v in range(a, 200)]          # to the chapter end; the rest is the next chapter
    return [(c, v) for v in range(a, b + 1)]


def book_moods(book: str, facts: list[dict], rows: list[dict], to_ed, layout: dict) -> dict[int, Mood]:
    """Edition chapter -> its mood, for every chapter of the book that has one."""
    out: dict[int, Mood] = {}
    for _, mid, m in chapter_moods(book, facts, rows, layout):
        e = to_ed(mid)
        if e is not None:
            out[e[0]] = m
    return out


def chapter_moods(book: str, facts: list[dict], rows: list[dict],
                  layout: dict) -> list[tuple[int, tuple[int, int], Mood]]:
    """(spine chapter, its middle verse, its mood) for every chapter of the book that has one. The
    middle verse says which edition chapter the mood goes to (through the verse map)."""
    cfg = toml("moods.toml")
    codes = textforms.codes()
    spine = sorted({(r["chapter"], r["verse"]) for r in rows})
    by_ch: dict[int, list[tuple[int, int]]] = {}
    for cv in spine:
        by_ch.setdefault(cv[0], []).append(cv)

    def mid(c: int) -> tuple[int, int]:
        vs = by_ch.get(c) or [(c, 1)]
        return vs[len(vs) // 2]

    found: dict[int, list[Mood]] = {}
    order_all = cfg.get("priority", [])
    unknown_terms: set[str] = set()

    # 1. heading terms and halleluyah
    hd: dict[int, list[str]] = {}
    for f in facts:
        if f.get("kind") == "form" and f.get("value") in {**HEADING_MOODS, **HEADING_INSTRUMENTS}:
            hd.setdefault(int(f["first"][2:5]), []).append(f["value"])
    for c, vals in hd.items():
        moods = [HEADING_MOODS[v] for v in vals if v in HEADING_MOODS]
        inst = tuple(dict.fromkeys(HEADING_INSTRUMENTS[v] for v in vals if v in HEADING_INSTRUMENTS))
        terms = [codes.get(v, v).removeprefix("heading: ").removeprefix("mark: ").split(": a term of the text")[0]
                 for v in dict.fromkeys(vals)]
        found.setdefault(c, []).append(Mood(moods[0] if moods else None, "heading", "; ".join(terms), inst))

    # 2. a song in narrative (not a list set in song layout: fm.ms.song with layout "list")
    sv = structure.setting_verses(facts, spine, layout.get("setting"))
    share = layout.get("setting", {}).get("share", 0.5)
    not_songs = set(cfg.get("song", {}).get("not_songs", []))
    if len(sv["song"]) < share * max(len(spine), 1):          # the book itself is not song
        for c, vs in by_ch.items():
            n_song = sum(1 for cv in vs if cv in sv["song"])
            if n_song >= share * len(vs) and f"{book} {c}" not in not_songs:
                found.setdefault(c, []).append(Mood("song", "song", f"Masoretic song layout over {n_song} of {len(vs)} verses"))

    # 3. a psalm's type (Tyndale, fm.gn.*) and purpose (Scriptura, fm.pu.*), by their Hebrew terms
    for basis, prefix, who in (("type", "fm.gn.", "Tyndale Open Study Notes"), ("purpose", "fm.pu.", "Scriptura")):
        tcfg = cfg.get(basis, {})
        terms = tcfg.get("terms", {})
        bad = sorted(m for m in terms.values() if m and m not in order_all)
        if bad:
            raise ConfigError(f"config/moods.toml [{basis}.terms]: mood(s) {', '.join(bad)} not in priority")
        tcover: dict[int, dict[str, set]] = {}
        for f in facts:
            v = f.get("value", "")
            if f.get("kind") == "form" and v.startswith(prefix):
                term = v[len(prefix):]
                if term not in terms:
                    unknown_terms.add(f"{v} ({f.get('head', '')})")
                    continue
                if not terms[term]:
                    continue
                for cv in _verses(f["ref"]):
                    if cv in by_ch.get(cv[0], ()):
                        tcover.setdefault(cv[0], {}).setdefault(term, set()).add(cv)
        for c, ts in tcover.items():
            n = len(by_ch[c])
            named = {t: vs for t, vs in ts.items() if len(vs) >= tcfg.get("min_share", 0.5) * n}
            if not named or len(named) > tcfg.get("max_types", 2):    # no type, or no one clear type
                continue
            for term, vs in named.items():
                head = next((f.get("head") for f in facts if f.get("value") == prefix + term and f.get("head")), "")
                found.setdefault(c, []).append(Mood(terms[term], basis, f"{who}: {term} {head}".rstrip()
                                                    + f" over {len(vs)} of {n} verses", share=len(vs) / n))

    # 4. what the classical commentators say the psalm is (hebrew-commentary-terms, by rule and model-read)
    ccfg = cfg.get("commentary", {})
    if ccfg.get("use", True):
        roots = ccfg.get("roots", {})
        bad = sorted(m for m in roots.values() if m and m not in order_all)
        if bad:
            raise ConfigError(f"config/moods.toml [commentary.roots]: mood(s) {', '.join(bad)} not in priority")
        datasets = set(ccfg.get("datasets", structure.COMMENTARY_DATASETS))
        said: dict[int, dict[str, dict[str, str]]] = {}        # chapter -> mood -> witness -> term
        for r in structure.commentary_statements(book, "kind"):
            if r["dataset"] not in datasets or not r.get("term"):
                continue
            m = commentary_mood(r["term"], roots)
            if m:
                said.setdefault(int(r["subject_first"][2:5]), {}).setdefault(m, {}).setdefault(
                    r["witness"] + ("*" if r.get("model") else ""), r["term"])
        for c, by_mood in said.items():
            if c not in by_ch:
                continue
            ranked = sorted(by_mood.items(), key=lambda x: -len({w.rstrip("*") for w in x[1]}))
            m, ws = ranked[0]
            nw = len({w.rstrip("*") for w in ws})
            if nw < ccfg.get("min_witnesses", 1) or (len(ranked) > 1 and len({w.rstrip("*") for w in ranked[1][1]}) == nw):
                continue                                   # too few, or the commentators split evenly
            ev = ", ".join(f"{WITNESSES.get(w.rstrip('*'), w.rstrip('*'))}{' (model-read)' if w.endswith('*') else ''}: {t}"
                           for w, t in ws.items())
            found.setdefault(c, []).append(Mood(m, "commentary", f"Hebrew commentators: {ev}"))

    # 5. delivery covering most of the chapter
    dcfg = cfg.get("delivery", {})
    group_of = {}
    for g, labels in dcfg.get("groups", {}).items():
        for lab in labels:
            group_of[lab] = g
    known = set(codes.values())
    bad = sorted(lab for lab in group_of if lab not in known)
    if bad:
        raise ConfigError(f"config/moods.toml [delivery.groups]: unknown delivery label(s) {', '.join(bad)} "
                          "(use the labels of passage-facts codes.tsv, e.g. \"lament\", \"praying\")")
    cover: dict[int, dict[str, set]] = {}
    for f in facts:
        if f.get("kind") != "delivery":
            continue
        g = group_of.get(codes.get(f["value"], ""))
        if g:
            for cv in _verses(f["ref"]):
                if cv in by_ch.get(cv[0], ()):
                    cover.setdefault(cv[0], {}).setdefault(g, set()).add(cv)
    min_share = dcfg.get("min_share", 0.4)
    for c, groups in cover.items():
        g, vs = max(groups.items(), key=lambda x: len(x[1]))
        n = len(by_ch[c])
        if len(vs) >= min_share * n:
            found.setdefault(c, []).append(Mood(g, "delivery", f"speech delivered as {g} over {len(vs)} of {n} verses"))

    if unknown_terms:
        print(f"note: {book}: passage-facts term(s) not in config/moods.toml, no mood from them: "
              f"{', '.join(sorted(unknown_terms))}", file=sys.stderr)

    # one mood per chapter: the cue first in ``sources``, then the one covering most of the chapter,
    # then the mood first in ``priority``;
    # instruments are kept from the heading
    order = order_all
    sources = cfg.get("sources", ["heading", "song", "type", "purpose", "commentary", "delivery"])
    out: list[tuple[int, tuple[int, int], Mood]] = []
    for c, ms in found.items():
        with_mood = sorted((m for m in ms if m.mood),
                           key=lambda m: (sources.index(m.basis) if m.basis in sources else len(sources), -m.share,
                                          order.index(m.mood) if m.mood in order else len(order)))
        inst = tuple(dict.fromkeys(i for m in ms for i in m.instruments))
        best = with_mood[0] if with_mood else ms[0]
        ev = "; ".join(dict.fromkeys([best.evidence] + [m.evidence for m in ms]))
        out.append((c, mid(c), Mood(best.mood, best.basis, ev, inst)))
    return out


WITNESSES = {"radak": "Radak", "meiri": "Meiri", "ibn_ezra": "Ibn Ezra", "rashi": "Rashi", "malbim": "Malbim",
             "metzudat_david": "Metzudat David", "metzudat_zion": "Metzudat Zion"}
_POINTS = re.compile(r"[\u0591-\u05C7]")


def commentary_mood(term: str, roots: dict[str, str]) -> str | None:
    """The mood a commentator's term gives: the first root of moods.toml [commentary.roots] whose
    letters stand in the term (pointing ignored; התפלה, ומתפלל, תפלתו all hold תפל)."""
    t = _POINTS.sub("", term)
    for root, mood in roots.items():
        if root in t:
            return mood or None
    return None


def apply_overrides(book: str, found: dict[int, Mood], profile) -> dict[int, Mood]:
    """The [chapters.N] blocks of config/books/<BOOK>.toml laid over the source's moods."""
    out = dict(found)
    for n, ch in (config_book(book).get("chapters") or {}).items():
        c = int(n)
        src = found.get(c)
        where = f"config/books/{book}.toml [chapters.{c}]"
        if "style" in ch:
            out[c] = Mood(src.mood if src else None, "manual", where, (), ch["style"])
        elif "mood" in ch:
            m = ch["mood"]
            if not m:
                out.pop(c, None)
                continue
            if m not in (profile.moods or {}):
                raise ConfigError(f"{where}: mood {m!r} is not in config/profiles.toml [moods]; "
                                  f"choose from {', '.join(profile.moods or {})}")
            out[c] = Mood(m, "manual", where + (f" (the source: {src.evidence})" if src else ""),
                          src.instruments if src else ())
    return out


def chapter_style(profile, mood: Mood | None) -> tuple[str, str | None]:
    """(the chapter's style line, the words its mood added, or None when it keeps the book style)."""
    if mood is None:
        return profile.style, None
    if mood.style:
        return mood.style, "its own style line"
    words = [w for w in ([profile.moods.get(mood.mood, "")] if mood.mood else [])
             + [profile.instruments.get(i, "") for i in mood.instruments] if w]
    if not words:
        return profile.style, None
    added = ", ".join(words)
    return f"{profile.base_style}, {added}{profile.suffix}", added


# The scholarly sources a mood can come from: the name in the evidence -> passage-facts sources.tsv id.
SOURCES = {"Tyndale Open Study Notes": "tyndale", "Scriptura": "scriptura"}


def scholarly_sources() -> dict[str, str]:
    """passage-facts sources.tsv id -> how it asks to be credited, for the scholarly sources a
    mood can come from (SOURCES)."""
    import csv
    from . import fetch
    rows = {}
    for r in csv.reader(fetch.hf("passage-facts", "sources.tsv").read_text(encoding="utf-8").splitlines(),
                        delimiter="\t"):
        if r and not r[0].startswith("#") and len(r) > 5:
            rows[r[0]] = r[5] if r[2] in r[5] else f"{r[5]} ({r[2]})"
    return {sid: rows[sid] for sid in SOURCES.values() if sid in rows}


def source_credits(mood: Mood | None, section: list | None, pins: dict, sources: dict[str, str]) -> list[str]:
    """The attribution each source of the chapter's mood and its section moods asks for: the
    scholarly sources in the wording of passage-facts sources.tsv (``sources``, from the plan), and
    the model-read datasets (``pins``: the plan's dataset pins)."""
    out = []
    def ds(name: str, what: str) -> str:
        return f"{what}: bcv-commons/{name} {pins[name]['tag']}, {pins[name]['licence']}"
    if mood and "Hebrew commentators" in mood.evidence:
        out.append(ds("hebrew-commentary-terms", "what the Hebrew commentators call the psalm")
                   + " (commentaries from Sefaria, https://www.sefaria.org, Public Domain or CC0)")
        if "(model-read)" in mood.evidence:
            out.append(ds("hebrew-commentary-terms-model", "their statements read by a model"))
    sm = [m for m in (section or []) if m]
    if sm:
        out.append("section moods: bcv-commons/passage-facts mood families (UBS dictionaries SDBH and Louw-Nida, "
                   "CC BY-SA 4.0)")
        if any(m.model for m in sm):
            out.append(ds("passage-moods-model", "section moods read by a model"))
    if not mood:
        return out
    return [sources[sid] for name, sid in SOURCES.items() if name in mood.evidence and sid in sources] + out


@dataclass
class SectionMood:
    family: str          # md.* feeling family
    head: str            # its Hebrew/Greek head word
    tag: str             # what is written in the lyrics
    evidence: str        # which facts gave it
    model: bool          # read by a model (passage-moods-model)


def _span_verses(first: str, last: str, spine: list[tuple[int, int]]) -> list[tuple[int, int]]:
    a, b = structure.key_cv(first), structure.key_cv(last)
    return [cv for cv in spine if a <= cv <= b]


def _cvs(vs: list[tuple[int, int]]) -> str:
    (c1, v1), (c2, v2) = vs[0], vs[-1]
    return f"{c1}:{v1}" if (c1, v1) == (c2, v2) else f"{c1}:{v1}-{v2}" if c1 == c2 else f"{c1}:{v1}-{c2}:{v2}"


def runs(verses: list[tuple[int, int]]) -> list[list[int]]:
    """Spine verses as runs [chapter, first verse, last verse] (a song plan's compact form)."""
    out: list[list[int]] = []
    for c, v in verses:
        if out and out[-1][0] == c and out[-1][2] == v - 1:
            out[-1][2] = v
        else:
            out.append([c, v, v])
    return out


def unrun(rs: list[list[int]]) -> list[tuple[int, int]]:
    return [(c, v) for c, a, b in rs for v in range(a, b + 1)]


def mood_spans(book: str, facts: list[dict], spine: list[tuple[int, int]]) -> tuple[list[dict], list[dict]]:
    """The spans section_moods weighs, as a song plan holds them: (passage-facts ``mood`` facts,
    passage-moods-model rows), each with the spine verses it covers (as runs)."""
    pf = [{"n": n, "family": f["value"], "head": f.get("head", ""),
           "verses": runs(_span_verses(f["first"], f["last"], spine))}
          for n, f in enumerate(facts) if f.get("kind") == "mood" and f.get("value", "").startswith("md.")]
    model = [{"m": n, "moods": [{"family": m["family"], "head": m.get("head", "")} for m in r["moods"] or []],
              "verses": runs(_span_verses(r["first"], r["last"], spine))}
             for n, r in enumerate(structure.model_moods(book))]
    return pf, model


def section_moods(book: str, sections_verses: list[list[tuple[int, int]]], mood_facts: list[dict],
                  model_moods: list[dict], to_ed, profile) -> list[SectionMood | None]:
    """A feeling for each section of a chapter, where the Hebrew/Greek words of most of its verses
    mark one (passage-facts ``mood`` facts, by rule; passage-moods-model, read by a model), from
    the spans of the song plan (mood_spans). Rules: config/moods.toml [section_moods]; the words of
    each tag: profiles.toml [families]."""
    cfg = toml("moods.toml").get("section_moods", {})
    if not cfg.get("use", True):
        return [None] * len(sections_verses)
    weights = cfg.get("model_weights", [1.0, 0.5, 0.33])
    spans: list[tuple[str, str, set, float, bool, str]] = []    # family, head, edition verses, weight, model, source
    for f in mood_facts:
        ev = {e for e in map(to_ed, unrun(f["verses"])) if e}
        spans.append((f["family"], f["head"], ev, 1.0, False, "passage-facts"))
    if cfg.get("use_model", True):
        for r in model_moods:
            ev = {e for e in map(to_ed, unrun(r["verses"])) if e}
            for i, m in enumerate(r["moods"]):
                if i < len(weights):
                    spans.append((m["family"], m["head"], ev, weights[i], True, "passage-moods-model"))
    families = profile.families or {}
    out: list[SectionMood | None] = []
    for vs in sections_verses:
        V = set(vs)
        score: Counter = Counter()
        cover: dict[str, set] = {}
        why: dict[str, list] = {}
        for fam, head, ev, w, model, src in spans:
            ov = V & ev
            if ov:
                score[fam] += w * len(ov)
                cover.setdefault(fam, set()).update(ov)
                why.setdefault(fam, []).append((head, model, f"{src} {book} {_cvs(sorted(ev))}"))
        best = max(score, key=lambda f: (score[f], f), default=None)
        if (not best or len(cover[best]) < cfg.get("min_share", 0.5) * len(V) or not families.get(best)):
            out.append(None)
            continue
        ws = why[best]
        srcs = list(dict.fromkeys(src for _, _, src in ws))
        out.append(SectionMood(best, ws[0][0], profile.family_tag.format(words=families[best]),
                               "; ".join(srcs), any(m for _, m, _ in ws)))
    return out


def summary(moods: dict[int, Mood]) -> Counter:
    return Counter(m.mood or "instrument" for m in moods.values())
