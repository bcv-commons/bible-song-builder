"""Reading the files in config/: TOML for settings, CSV for the cast table.

Every file is meant to be edited by hand, so a mistake is reported with the file and the row
or key, and what is allowed there.
"""
from __future__ import annotations

import csv
import tomllib
from functools import lru_cache
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "config"

VOICES = ("narrator", "female", "male", "group", "female_group", "divine")
CAST_FILE = "cast.csv"
CAST_COLUMNS = ["speaker_id", "voice", "basis", "name", "source", "words", "books"]   # then label_<EDITION>..., note


class ConfigError(SystemExit):
    pass


@lru_cache(maxsize=None)
def toml(name: str) -> dict:
    path = CONFIG / name
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        raise ConfigError(f"config/{name} is missing") from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"config/{name}: {e}") from None


def merge(a: dict, b: dict) -> dict:
    """``a`` with ``b`` laid over it, table by table."""
    out = dict(a)
    for k, v in (b or {}).items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def edition(name: str | None) -> dict:
    """The edition's block of editions.toml ({} if it has none)."""
    return toml("editions.toml").get(name, {}) if name else {}


@lru_cache(maxsize=None)
def layout(edition_name: str | None = None) -> dict:
    """layout.toml, overridden by the edition's language (languages.toml [<iso>.layout]) and
    then by the edition itself (editions.toml [<EDITION>.layout])."""
    out = toml("layout.toml")
    if edition_name:
        from .fetch import pins
        iso = pins()["editions"].get(edition_name, {}).get("iso")
        out = merge(out, language(iso).get("layout", {}) if iso else {})
        out = merge(out, edition(edition_name).get("layout", {}))
    return out


BOOK_KEYS = {"profile", "lead", "style", "chapters"}
CHAPTER_KEYS = {"mood", "style"}


@lru_cache(maxsize=None)
def book(code: str) -> dict:
    """config/books/<BOOK>.toml, laid over config/books/_default.toml."""
    out = dict(toml("books/_default.toml"))
    path = CONFIG / "books" / f"{code}.toml"
    if path.exists():
        own = toml(f"books/{code}.toml")
        bad = sorted(set(own) - BOOK_KEYS)
        if bad:
            raise ConfigError(f"config/books/{code}.toml: unknown setting(s) {', '.join(bad)}; "
                              f"allowed: {', '.join(sorted(BOOK_KEYS))} and [chapters.N] blocks")
        for n, ch in (own.get("chapters") or {}).items():
            if not str(n).isdigit() or not isinstance(ch, dict):
                raise ConfigError(f"config/books/{code}.toml: [chapters.{n}]: use the chapter number, e.g. [chapters.23]")
            bad = sorted(set(ch) - CHAPTER_KEYS)
            if bad:
                raise ConfigError(f"config/books/{code}.toml [chapters.{n}]: unknown setting(s) {', '.join(bad)}; "
                                  f"allowed: {', '.join(sorted(CHAPTER_KEYS))}")
        out.update(own)
    return out


def chapter(code: str, n: int) -> dict:
    """The [chapters.N] block of config/books/<BOOK>.toml ({} if none)."""
    return (book(code).get("chapters") or {}).get(str(n), {})


def cast_rules() -> dict:
    return toml("cast-rules.toml")


def language(iso: str) -> dict:
    return toml("languages.toml").get(iso, {})


CAST_GENERATED = CONFIG.parent / "cache" / "cast" / "cast.csv"     # built from the data (bible_song_builder.castbuild)
OVERRIDE_COLUMNS = ["speaker_id", "voice", "name", "note"]


def _read_csv(path: Path, label: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8-sig", newline="") as f:       # -sig: the BOM Excel writes
        for n, row in enumerate(csv.DictReader(f), start=2):
            sid = (row.get("speaker_id") or "").strip()
            if not sid:
                continue
            voice = (row.get("voice") or "").strip()
            if voice and voice not in VOICES:
                raise ConfigError(f"{label} row {n} ({sid}, {row.get('name')}): voice {voice!r} "
                                  f"is not one of {', '.join(VOICES)}")
            row = {k: (v or "").strip() for k, v in row.items() if k}
            row["voice"] = voice
            out[sid] = row
    return out


def cast_overrides() -> dict[str, dict]:
    """config/cast.csv: the hand decisions (speaker_id, voice, name, note), nothing else."""
    return _read_csv(CONFIG / CAST_FILE, f"config/{CAST_FILE}")


@lru_cache(maxsize=None)
def cast_table() -> dict[str, dict]:
    """speaker_id -> row: the generated table (cache/cast/cast.csv) with config/cast.csv laid over
    it. A row set by hand gets basis "manual". Empty if the table is not built yet."""
    out = _read_csv(CAST_GENERATED, "cache/cast/cast.csv")
    for sid, o in cast_overrides().items():
        row = dict(out.get(sid, {"speaker_id": sid}))
        for k in ("voice", "name", "note"):
            if o.get(k):
                row[k] = o[k]
        row["basis"] = "manual"
        out[sid] = row
    return out


def write_cast(rows: list[dict], editions: list[str], path: Path = CAST_GENERATED) -> Path:
    """Write a cast table (UTF-8 with BOM, so Excel shows Hebrew and Greek correctly)."""
    cols = CAST_COLUMNS + [f"label_{e}" for e in editions] + ["note"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})
    cast_table.cache_clear()
    return path
