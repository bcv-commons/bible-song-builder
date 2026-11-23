"""Suno lyrics: sections with voice tags, and the notes that go with them.

The style line and the voice tags come from the book's profile (config/profiles.toml,
config/books.toml), so every chapter of a book sounds alike. A voice tag names a kind of voice
(config/cast.csv gives each speaker's class), never a person; who each tag stands for is
listed in the notes file.

Every lyric line is the edition's own text, verbatim. Nothing is shortened, paraphrased or
added here. A later writing step that shortens must list what it changed in the comment
block. Section labels come from the data: [Verse n] for each stanza, [Bridge] for a stanza
the facts set as song or poetic lines inside a prose chapter, and [Chorus] for a line the
chapter itself repeats (at least ``CHORUS_MIN`` times), in the places it occurs.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .lines import LyricLine, Stanza
from .profiles import Profile

@dataclass
class Section:
    label: str
    stanza: Stanza
    sung: bool
    refrain: set[str] = field(default_factory=set)   # refrain ids sung inside the section (responsorial)
    kind: str = "start"      # why the section starts (see lines.Stanza.reason)
    mood: object = None      # moods.SectionMood: a feeling the words of this section mark


def _norm(s: str) -> str:
    return " ".join(re.findall(r"[^\W\d_]+", s.lower()))


def repeated_lines(lines: list[LyricLine], min_repeats: int, min_words: int) -> set[str]:
    """Edition lines repeated word for word (chorus source "lines")."""
    c = Counter(_norm(ln.text) for ln in lines)
    return {t for t, n in c.items() if n >= min_repeats and len(t.split()) >= min_words}


def sections(stanzas: list[Stanza], setting: str, sung_verses: set[tuple[int, int]],
             chorus: dict | None = None) -> list[Section]:
    """Sections from stanzas. A chorus line is a refrain line: one the Hebrew/Greek repeats
    (``line.refrain``, chorus.source "text"), or one the edition repeats ("lines"), or either
    ("both"). A stanza in which a chorus line comes back is kept whole, as call and response;
    otherwise the stanza is cut around its chorus lines."""
    chorus = chorus or {}
    src = chorus.get("source", "text")
    all_lines = [ln for s in stanzas for ln in s.lines]
    if src == "lines":
        for ln in all_lines:
            ln.refrain = None
    if src in ("lines", "both"):
        rep = repeated_lines(all_lines, chorus.get("lines_min_repeats", 3), chorus.get("lines_min_words", 3))
        for ln in all_lines:
            if ln.refrain is None and _norm(ln.text) in rep:
                ln.refrain = "rep:" + _norm(ln.text)
    ids = {ln.refrain for ln in all_lines if ln.refrain}

    inline = chorus.get("style", "section") == "inline"

    def occurrences(lns: list[LyricLine]) -> int:
        """How often the same refrain starts in these lines, for the refrain that starts most
        (one occurrence may run over several lines)."""
        occ = {ln.refrain for ln in lns if ln.refrain}            # "<refrain>#<occurrence>"
        c = Counter(r.split("#")[0] for r in occ)
        return max(c.values(), default=0)

    out: list[Section] = []
    n = 0
    for st in stanzas:
        vs = st.verses
        sung = sum(1 for v in vs if v in sung_verses) * 2 > len(vs)
        label_sung = setting != "prose" or sung
        if occurrences(st.lines) >= (1 if inline else 2):
            # the refrain returns inside the stanza: keep it whole, call and response
            if setting == "prose" and sung:
                out.append(Section("Bridge", st, True, refrain=ids, kind=st.reason))
            else:
                n += 1
                out.append(Section(f"Verse {n}", st, label_sung, refrain=ids, kind=st.reason))
            continue
        # cut the stanza around its chorus line
        runs: list[tuple[bool, list[LyricLine]]] = []
        for ln in st.lines:
            is_ch = ln.refrain is not None
            if runs and runs[-1][0] == is_ch:
                runs[-1][1].append(ln)
            else:
                runs.append((is_ch, [ln]))
        # a single line left over in the verse right after a chorus stays with it ("— the first day")
        k = 1
        while k < len(runs):
            if (runs[k - 1][0] and not runs[k][0] and len(runs[k][1]) == 1
                    and runs[k][1][0].cv == runs[k - 1][1][-1].cv):
                runs[k - 1][1].extend(runs[k][1])
                del runs[k]
                if k < len(runs) and runs[k][0] == runs[k - 1][0]:
                    runs[k - 1][1].extend(runs[k][1])
                    del runs[k]
            else:
                k += 1
        for k, (is_ch, lns) in enumerate(runs):
            kind = st.reason if k == 0 else ("midverse" if lns[0].cv == runs[k - 1][1][-1].cv else "chorus")
            if is_ch:
                out.append(Section("Chorus", Stanza(lns, kind), True, kind=kind))
                continue
            if setting == "prose" and sung:
                out.append(Section("Bridge", Stanza(lns, kind), True, kind=kind))
            else:
                n += 1
                out.append(Section(f"Verse {n}", Stanza(lns, kind), setting != "prose", kind=kind))
    return out


def _range(book_name: str, verses: list[tuple[int, int]]) -> str:
    (c1, v1), (c2, v2) = verses[0], verses[-1]
    if (c1, v1) == (c2, v2):
        return f"{c1}:{v1}"
    return f"{c1}:{v1}-{v2}" if c1 == c2 else f"{c1}:{v1}-{c2}:{v2}"


def voice_of(ln: LyricLine) -> str:
    if ln.quote is None:
        return "narrator"
    return ln.speaker.voice if ln.speaker else "narrator"


def section_tag(label: str, mode: str = "all", number_verses: bool = True) -> str | None:
    """The tag written for a section, or None (layout.toml [sections])."""
    if mode == "none":
        return None
    if label.startswith("Verse"):
        if mode == "chorus_bridge":
            return None
        return f"[{label}]" if number_verses else "[Verse]"
    return f"[{label}]"


def render(book_name: str, chapter: int, edition_name: str, setting: str, secs: list[Section],
           credits: list[str], profile: Profile, style: str | None = None, max_chars: int = 5000,
           extra_notes: list[str] | None = None, names=None, layout: dict | None = None,
           letter_names: dict[str, str] | None = None, style_note: str | None = None) -> tuple[str, str]:
    """(the notes, the lyrics). The notes go in their own file; the lyrics are what is pasted
    into Suno's Lyrics box, and the style line (its own file) into the Style of Music box.

    A tag is written where the voice changes: to another speaker, or back to the narrator
    (the persona's lead). The lyrics open without a tag when the narrator starts.
    ``names(speaker) -> str`` gives the readable name listed in the notes file."""
    layout = layout or {}
    sec_cfg = layout.get("sections", {})
    mode, numbered = sec_cfg.get("tags", "all"), sec_cfg.get("number_verses", True)
    selah_tag = layout.get("psalms", {}).get("selah_tag", "")
    tags = profile.tags
    body: list[str] = []
    cast_used: dict[str, list[str]] = {}
    cur_key, cur_tag = None, tags.get("narrator")
    cur_mood = None
    for s in secs:
        if body:
            body.append("")
        head = section_tag(s.label, mode, numbered)
        if head:
            body.append(head)
        mood_tag = s.mood.tag if s.mood else None
        if mood_tag and mood_tag != cur_mood:      # a mood tag where the feeling changes
            body.append(mood_tag)
        cur_mood = mood_tag
        for ln in s.stanza.lines:
            is_refrain = ln.refrain is not None and ln.refrain in s.refrain
            if is_refrain:
                key, tag = ("refrain",), tags.get("refrain", "[Choir]")
            else:
                v = voice_of(ln)
                key = None if v == "narrator" else (ln.speaker.id if ln.speaker and ln.speaker.id else ln.quote)
                tag = tags.get(v, "")
                if v != "narrator" and ln.speaker:
                    who = (names(ln.speaker) if names else None) or ln.speaker.label or ln.speaker.id or "unnamed"
                    lst = cast_used.setdefault(tag, [])
                    if who not in lst:
                        lst.append(who)
            if key != cur_key and tag and (tag != cur_tag or key is not None):
                body.append(tag)
            cur_key, cur_tag = key, tag
            body.append(ln.text)
            if ln.selah and selah_tag:
                body.append(selah_tag)
    lyrics = "\n".join(body) + "\n"

    notes = [f"{book_name} {chapter} · {edition_name} · setting: {setting}",
             f"Profile: {profile.name}, {profile.lead} lead · Suno persona: "
             + (profile.persona or f"(not set: profiles.toml [profiles.{profile.name}] persona.{profile.lead})")]
    if style_note:
        notes.append(style_note)
    if cast_used:
        notes.append("Voices: " + "; ".join(f"{t} {', '.join(w)}" for t, w in cast_used.items())
                     + f"; {tags.get('narrator')} or no tag = the narrator (the persona)")
    if mode != "all":
        notes.append(f"Section tags: {mode} (layout.toml); the sections are still listed here")
    for s in secs:
        letters = [ln.acrostic for ln in s.stanza.lines if ln.acrostic]
        let = ("  · " + ", ".join(f"{x} {(letter_names or {}).get(x, '')}".strip() for x in letters)) if letters else ""
        md = (f"  · {s.mood.tag} {s.mood.family} {s.mood.head}, from {s.mood.evidence}"
              + (" (model-read)" if s.mood.model else "")) if s.mood else ""
        notes.append(f"[{s.label}] {_range(book_name, s.stanza.verses)}{let}{md}")
    notes.extend(extra_notes or [])
    notes.append("Shortened or paraphrased: nothing; every line is the edition's text, verbatim.")
    if len(lyrics) > max_chars:
        notes.append(f"Length: {len(lyrics)} characters, over {max_chars}; shorten before use and list the cuts here.")
    notes.extend(credits)
    return "\n".join(notes) + "\n", lyrics
