"""The join: which target tokens each Hebrew/Greek word (a MACULA key) aligned to.

Preferred: the hand-made full alignment (bcv-commons/full-alignments-manual, layer
``eng_BSB+manual+bsb-tables``), which links every source token, function words included,
and names the words the editor supplied (``+``). Fallback: the compact statistical
alignment (content words only). If the edition's text has no file under its fingerprint,
there is no alignment and the caller breaks at verse ends only.

Arrays are keyed by SPINE verse (WLC / Nestle 1904 numbering); target positions are in the
EDITION verse the verse map gives (spine PSA 3:2 = English PSA 3:1).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import fetch


@dataclass
class Alignment:
    kind: str                                   # "full", "compact" or "none"
    layer: str | None
    file: str | None
    # edition chapters whose text differs from the aligned text: no alignment there
    chapters_off: set[int] = field(default_factory=set)
    # MACULA key -> (edition (chapter, verse), set of target token positions)
    links: dict[str, tuple[tuple[int, int], set[int]]] = field(default_factory=dict)

    def positions(self, key: str) -> tuple[tuple[int, int], set[int]] | None:
        hit = self.links.get(key)
        return hit if hit and hit[1] else None


def parse_span(s: str) -> list[int]:
    """``5``, ``5-7``, ``5,9``, ``L3,1,2``; ``~`` and ``!`` are no positions."""
    if s.startswith("L"):
        s = s[1:]
    out: list[int] = []
    for part in s.split(","):
        if not part or part in ("~", "!"):
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            if a.isdigit() and b.isdigit():
                out.extend(range(int(a), int(b) + 1))
        elif part.isdigit():
            out.append(int(part))
    return out


def _ref_to_cv(ref: str) -> tuple[int, int] | None:
    _, cv = ref.split(" ", 1)
    c, v = cv.split(":")
    return (int(c), int(v)) if v.isdigit() else None   # "C:title" has no target words


def verse_map(edition: str) -> dict[str, str]:
    """Spine ref -> edition ref, for every verse whose numbering differs."""
    name = fetch.pins()["editions"][edition]["verse_map"]
    return fetch.hf_json("compact-alignments", f"_index/{name}")["map"]


def spine_to_edition(vmap: dict[str, str], book: str, cv: tuple[int, int]) -> tuple[int, int] | None:
    ref = f"{book} {cv[0]}:{cv[1]}"
    return _ref_to_cv(vmap.get(ref, ref))


def published_fingerprints(edition: str, book: str) -> tuple[str, dict[int, str]] | None:
    """The aligned text's book hash and 5-hex chapter fingerprints, from the edition's
    ``_fingerprints.txt`` in compact-alignments-meta (the latest aligned version)."""
    ed = fetch.pins()["editions"][edition]
    iso = ed["iso"]
    try:
        txt = fetch.hf("compact-alignments-meta", f"{iso[0]}/{iso}/{ed['compact_edition']}/_fingerprints.txt")
    except fetch.NotFound:
        return None
    for line in txt.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if parts and parts[0] == book:
            chapters, n = {}, 1
            for tok in parts[3:]:
                if ":" in tok:
                    n_s, tok = tok.split(":", 1)
                    n = int(n_s)
                chapters[n] = tok
                n += 1
            return parts[1], chapters
    return None


def load(edition: str, book: str, file_hash: str, chapter_fps: dict[int, str] | None = None) -> Alignment:
    """The alignment of exactly this text. If the book's fingerprint has no file, the latest
    aligned version is used for the chapters whose chapter fingerprint matches ours, and the
    others are marked ``chapters_off`` (compact-alignments README, "Client rule")."""
    al = _load(edition, book, file_hash)
    if al.kind != "none" or not chapter_fps:
        return al
    pub = published_fingerprints(edition, book)
    if not pub or pub[0] == file_hash:
        return al
    al = _load(edition, book, pub[0])
    al.chapters_off = {c for c, fp in chapter_fps.items() if pub[1].get(c) != fp[:5]}
    if al.chapters_off:
        off = {k for k, (cv, _) in al.links.items() if cv[0] in al.chapters_off}
        for k in off:
            del al.links[k]
    return al


def _load(edition: str, book: str, file_hash: str) -> Alignment:
    ed = fetch.pins()["editions"][edition]
    iso = ed["iso"]
    lexemes = fetch.hf_json("compact-alignments", f"_index/{book}_lexemes.json")
    refs = list(lexemes)
    keys = fetch.hf_json("compact-alignments", f"_index/{book}_keys.json")
    vmap = verse_map(edition)

    main = fn = None
    kind = "none"
    layer = path = None
    if ed.get("full_layer"):
        layer = ed["full_layer"]
        path = f"{iso[0]}/{iso}/{layer}/{book}_{file_hash}.json"
        try:
            main = fetch.hf_json("full-alignments-manual", path)
            fn = fetch.hf_json("full-alignments-manual", path.replace(".json", ".meta.json"))["fn"]
            kind = "full"
        except fetch.NotFound:
            main = None
    if main is None and ed.get("compact_edition"):
        layer = ed["compact_edition"]
        path = f"{iso[0]}/{iso}/{layer}/{book}_{file_hash}.json"
        try:
            main = fetch.hf_json("compact-alignments", path)
            kind = "compact"
        except fetch.NotFound:
            main = None
    if main is None:
        return Alignment("none", None, None)

    fn_keys = fetch.hf_json("compact-alignments", f"_index/{book}_fn_keys.json") if fn else {}
    al = Alignment(kind, layer, path)

    def add(key_list: list[str], ordinal: int, target: tuple[int, int], pos: list[int]) -> None:
        if ordinal >= len(key_list):
            return
        for k in key_list[ordinal].split("+"):
            if k:
                al.links.setdefault(k, (target, set()))[1].update(pos)

    for i, ref in enumerate(refs):
        target = _ref_to_cv(vmap.get(ref, ref))
        if target is None:
            continue
        ck = keys.get(ref, [])
        fk = fn_keys.get(ref, []) if fn else []
        strings = [(main[i], ck, "c")] + ([(fn[i], fk, "f")] if fn else [])
        for s, klist, side in strings:
            for entry in s.split():
                head = entry[0]
                if head in "!ue":
                    continue                       # no target word of its own
                if head == "+":                    # supplied words, owned by a token: ">5" content, ">f3" function
                    for item in entry[1:].split(","):
                        if ">" not in item:
                            continue               # supplied for the grammar, no owner
                        pos, owner = item.split(">", 1)
                        if owner.startswith("f"):
                            add(fk, int(owner[1:]), target, [int(pos)])
                        else:
                            add(ck, int(owner), target, [int(pos)])
                    continue
                if ":" not in entry:
                    continue
                o, span = entry.split(":", 1)
                if o.isdigit():
                    add(klist, int(o), target, parse_span(span))
    return al
