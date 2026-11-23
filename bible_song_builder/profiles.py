"""Song profile of a book in an edition (config/profiles.toml, books/<BOOK>.toml, editions.toml)."""
from __future__ import annotations

import copy
from dataclasses import dataclass

from .config import VOICES, ConfigError, toml
from .config import book as book_config


@dataclass
class Profile:
    name: str
    lead: str                   # 'female' or 'male'
    style: str
    persona: str | None         # the Suno persona to select, if set
    tags: dict[str, str]        # voice class -> lyric tag
    base_style: str = ""        # the style without the edition's suffix
    suffix: str = ""            # the edition's style_suffix
    moods: dict[str, str] | None = None         # mood -> words added for a chapter with that mood
    instruments: dict[str, str] | None = None   # instrument -> words added
    families: dict[str, str] | None = None      # feeling family (md.*) -> words of its in-lyrics mood tag
    family_tag: str = "[Mood: {words}]"         # how that tag is written


def _merge(a: dict, b: dict) -> dict:
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def for_book(edition: str, book: str, profile: str | None = None, lead: str | None = None) -> Profile:
    profs = toml("profiles.toml")
    ed = toml("editions.toml").get(edition, {})

    pick: dict = {}
    bc = book_config(book)
    for layer in ({k: bc[k] for k in ("profile", "lead", "style") if k in bc},
                  ed.get("default"), ed.get("books", {}).get(book)):
        pick = _merge(pick, layer or {})
    name = profile or pick.get("profile")
    lead = lead or pick.get("lead") or "male"
    if name not in profs.get("profiles", {}):
        raise ConfigError(f"config/books/{book}.toml (or _default.toml, editions.toml): book {book} has profile {name!r}, which is not in "
                          f"config/profiles.toml; choose from {', '.join(profs.get('profiles', {}))}")
    if lead not in ("female", "male"):
        raise ConfigError(f"config/books/{book}.toml: lead {lead!r}; use \"female\" or \"male\"")

    p = _merge(profs["profiles"][name], ed.get("profiles", {}).get(name, {}))
    if not p.get("style"):
        raise ConfigError(f"config/profiles.toml: profile {name!r} has no style")
    tags = _merge(profs.get("tags", {}), p.get("tags", {}))
    unknown = sorted(set(tags) - set(VOICES) - {"refrain"})
    if unknown:
        raise ConfigError(f"config/profiles.toml: unknown voice tag name(s) {', '.join(unknown)} "
                          f"(profile {name}); allowed: {', '.join(VOICES)}, refrain")
    suffix = ed.get("style_suffix") or ""
    base = pick.get("style") or p["style"]          # a book's own style line wins over its profile's
    return Profile(name=name, lead=lead, style=base + suffix,
                   persona=(p.get("persona") or {}).get(lead) or None, tags=tags,
                   base_style=base, suffix=suffix,
                   moods=_merge(profs.get("moods", {}), p.get("moods", {})),
                   instruments=_merge(profs.get("instruments", {}), p.get("instruments", {})),
                   families=_merge(profs.get("families", {}), p.get("families", {})),
                   family_tag=p.get("family_tag", profs.get("family_tag", "[Mood: {words}]")))
