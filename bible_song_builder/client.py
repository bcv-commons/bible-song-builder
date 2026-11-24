"""The config a client reads (the JS projection, js/): config/ as one JSON file.

    python -m bible_song_builder.client            # -> dist/config.json

The TOML files are parsed and checked here, so a client needs no TOML reader:
  toml      every config/*.toml file, as parsed (books/ apart)
  books     config/books/<BOOK>.toml laid over _default.toml, checked (config.book); "_default" too
  cast      speaker_id -> {voice, name}: the cast table (generated, with config/cast.csv over it)
  pins      pins.json

Generated, never edited: a change goes in config/ and the file is built again.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import __version__, castbuild, config, fetch

DIST = fetch.ROOT / "dist"
SCHEMA = "1.0"


def bundle(edition_name: str = "BSB") -> dict:
    castbuild.ensure(edition_name)
    files = sorted(p.name for p in config.CONFIG.glob("*.toml"))
    codes = sorted(p.stem for p in (config.CONFIG / "books").glob("*.toml"))
    return {
        "schema": SCHEMA,
        "bible-song-builder": __version__,
        "toml": {name: config.toml(name) for name in files},
        "books": {code: config.book(code) for code in codes},
        "cast": {sid: {k: row[k] for k in ("voice", "name") if row.get(k)}
                 for sid, row in config.cast_table().items()},
        "pins": fetch.pins(),
    }


def write(path: Path = DIST / "config.json") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle(), ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    p = write(Path(sys.argv[1]) if len(sys.argv) > 1 else DIST / "config.json")
    print(f"{p.relative_to(fetch.ROOT)}  {p.stat().st_size // 1024} KB")
