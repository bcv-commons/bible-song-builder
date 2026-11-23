"""(Re)build the generated cast table, cache/cast/cast.csv, from the source data.

    python3 scripts/build_cast.py              # all books, edition BSB   (make cast)
    python3 scripts/build_cast.py --edition X  # also record edition X's names for the speakers
    python3 scripts/build_cast.py RUT          # only re-check the speakers of some books

A run of bible-song-builder builds the table by itself when it is missing or out of date; this script is
for doing it on purpose. Hand decisions are not made here but in config/cast.csv.
See bible_song_builder/castbuild.py.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from bible_song_builder import castbuild  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--edition", default="BSB")
    ap.add_argument("books", nargs="*", help="limit to these books (default: all)")
    a = ap.parse_args()
    castbuild.build(a.edition, a.books or None)
    castbuild.write_browse(ROOT / "output")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
