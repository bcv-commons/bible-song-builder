"""The cast: which kind of voice sings each speaker (config/cast.csv, config/cast-rules.toml).

A speaker is a ``speaker_id`` of the clause lines (one person across speeches, the same id in
every edition and language). Each gets a voice class: narrator, female, male, group,
female_group or divine. profiles.toml turns a class into a lyric tag.

cast.csv gives the class of each known id; a row with basis ``manual`` is a hand decision and is
never overwritten by scripts/build_cast.py. An id that is not listed (new data) is classed live
by cast-rules.toml, from the source data only:

1. group: the speech names several people (``speaker_members``, or ``speaker`` lists several
   lemmas), or the head word naming them is in ``group_words``. female_group if every person
   named is named with a word in ``female_words`` ("two daughters-in-law").
2. divine: at least ``divine.min_share`` of the speaker's quotes (and ``divine.min_quotes``)
   carry passage-facts' ``divine`` flag.
3. the speaking verb: the verb that introduces the speaker's quotes (passage-facts ``frame``)
   is plural (group; female_group if feminine), feminine (female) or masculine (male), in at
   least ``verb.min_share`` of them. Gender is read only in ``verb.gender_from`` languages
   (Hebrew, Aramaic); Greek gives number only.
4. female: the head word naming the speaker (the first lemma of ``speaker``, or of
   ``speaker_name``) is in ``female_words``. Only the head counts: "the girl's father" is a man.
5. ``default``.

A quote with no speaker at all gets ``unknown``.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .config import VOICES, cast_rules, cast_table  # noqa: F401  (VOICES re-exported)


@dataclass
class SpeakerInfo:
    """What the source data says about one speaker, gathered over a book (or the Bible)."""
    lemmas: Counter = field(default_factory=Counter)     # `speaker`: lemmas of the words naming them
    names: Counter = field(default_factory=Counter)      # `speaker_name`: their proper name
    members: bool = False
    quotes: int = 0
    divine: int = 0
    verb: Counter = field(default_factory=Counter)        # the speaking verb's (gender, number)

    def add(self, other: "SpeakerInfo") -> None:
        self.lemmas.update(other.lemmas)
        self.names.update(other.names)
        self.members |= other.members
        self.quotes += other.quotes
        self.divine += other.divine
        self.verb.update(other.verb)


def speaker_id(row: dict) -> str | None:
    return row.get("speaker_id") or row.get("speaker") or None


def gather(rows: list[dict], facts: list[dict]) -> dict[str, SpeakerInfo]:
    out: dict[str, SpeakerInfo] = {}
    for r in rows:
        sid = speaker_id(r) if r.get("quotation") else None
        if not sid:
            continue
        info = out.setdefault(sid, SpeakerInfo())
        if r.get("speaker"):
            info.lemmas[r["speaker"]] += 1
        if r.get("speaker_name"):
            info.names[r["speaker_name"]] += 1
        info.members |= bool(r.get("speaker_members"))
    quote_speaker: dict[str, str] = {}
    for f in facts:
        if f.get("kind") != "quote":
            continue
        sid = f.get("speaker_id") or f.get("speaker")
        if not sid:
            continue
        quote_speaker[f["id"]] = sid
        info = out.setdefault(sid, SpeakerInfo())
        info.quotes += 1
        info.divine += bool(f.get("divine"))
    # the speaking verb of each quote (frame fact -> its quote by "of"), read in its clause row
    by_key = {k: r for r in rows for k in r["words"]}
    gender_from = set(cast_rules().get("verb", {}).get("gender_from", ["hbo", "arc"]))
    for f in facts:
        if f.get("kind") != "frame":
            continue
        sid = quote_speaker.get(f.get("of", ""))
        r = by_key.get(f["first"])
        if sid and r and (r.get("gender") or r.get("number")):
            # Greek participles agree with the noun ("a voice saying", φωνὴ λέγουσα), not with a person
            g = r.get("gender") if r.get("language") in gender_from else None
            out[sid].verb[(g, r.get("number"))] += 1
    return out


def _parts(lemma: str) -> list[list[str]]:
    """'אִשָּׁה אָדוֹן' -> [['אִשָּׁה', 'אָדוֹן']]; 'רָחֵל, לֵאָה' -> [['רָחֵל'], ['לֵאָה']] (one per person)."""
    return [p.split() for p in lemma.split(",") if p.strip()]


def rule_voice(info: SpeakerInfo, rules: dict | None = None) -> tuple[str, str]:
    """(voice class, basis) by the rules alone."""
    rules = rules or cast_rules()
    female = set(rules.get("female_words", []))
    groupw = set(rules.get("group_words", []))
    lemma = info.lemmas.most_common(1)[0][0] if info.lemmas else ""
    name = info.names.most_common(1)[0][0] if info.names else ""
    people = _parts(lemma) or _parts(name)
    heads = {p[0] for p in people} | {p[0] for p in _parts(name)}

    if info.members or len(people) > 1 or heads & groupw:
        all_female = bool(people) and all(set(p) & female for p in people)
        return ("female_group" if all_female else "group"), ("members" if info.members or len(people) > 1
                                                              else "group_word")
    dv = rules.get("divine", {})
    if info.quotes >= dv.get("min_quotes", 3) and info.divine >= dv.get("min_share", 0.8) * info.quotes:
        return "divine", "divine"
    vb = rules.get("verb", {})
    if vb.get("use", True) and info.verb:
        n = sum(info.verb.values())
        votes = Counter()
        for (g, num), c in info.verb.items():
            if num == "p":
                votes["female_group" if g == "f" else "group"] += c
            elif g in ("f", "m"):
                votes["female" if g == "f" else "male"] += c
        if votes:
            voice, c = votes.most_common(1)[0]
            if c >= vb.get("min_share", 0.6) * n:
                return voice, "verb"
    if heads & female:
        return "female", "female_word"
    return rules.get("default", "male"), "default"


def speaker_refs(rows: list[dict]) -> dict[str, dict]:
    """speaker_id -> the source words naming the speaker (``speaker_name_ref``: "named") and the
    words introducing them (``speaker_ref``: "described"): each different key list with the number
    of clause rows that give it, in the order they first occur. The edition's words for them are
    its label of the speaker (lines.speaker_labels)."""
    seen: dict[str, dict[str, dict[tuple[str, ...], int]]] = {}
    for r in rows:
        sid = speaker_id(r)
        if not sid:
            continue
        e = seen.setdefault(sid, {"named": {}, "described": {}})
        for field_, part in (("speaker_name_ref", "named"), ("speaker_ref", "described")):
            keys = tuple(r.get(field_) or [])
            if keys:
                e[part][keys] = e[part].get(keys, 0) + 1
    return {sid: {part: [[list(k), n] for k, n in d.items()] for part, d in e.items()} for sid, e in seen.items()}


def voice_of(sid: str | None, info: SpeakerInfo | None, rule: str | None = None) -> str:
    """The speaker's voice class: the cast table's, else ``rule`` (the voice a song plan gives by
    the rules), else the rules applied to ``info``."""
    rules = cast_rules()
    if not sid:
        return rules.get("unknown", "narrator")
    entry = cast_table().get(sid)
    if entry and entry.get("voice"):
        return entry["voice"]
    return rule or rule_voice(info or SpeakerInfo(), rules)[0]


def cast_name(sid: str | None) -> str | None:
    """The cast table's readable name for a speaker (for the notes file), if it has one."""
    entry = cast_table().get(sid or "")
    return (entry.get("name") or None) if entry else None
