"""Chapters over LIMIT chars: where can they be cut, at existing [Section] markers, into parts < LIMIT?

Each section boundary gets a kind:
  para   stanza end from the source (para_end / para_end_mam; NT: edition paragraph)
  split  stanza split by --max-lines at a verse start (heading / paragraph / voice change / middle)
  chorus inside a stanza, around a repeated line; 'midverse' if it is not at a verse start
Cuts: fewest parts (the greedy count), then the strongest boundaries, then the most even parts.
"""
import argparse, sys
from collections import Counter
from types import SimpleNamespace

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from bible_song_builder import align, edition, fetch, lines, plan, profiles, render, structure  # noqa: E402
from bible_song_builder.__main__ import build_chapter  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--limit", type=int, help="part size (default: layout.toml length.cut_limit)")
ap.add_argument("books", nargs="*")
a = ap.parse_args()
layout = __import__("bible_song_builder.config").config.layout("BSB")
LIMIT = a.limit or layout.get("length", {}).get("cut_limit", 4000)
MIN_PART = 1200
STRENGTH = {"acrostic": 4, "para": 3, "paragraph": 3, "split": 2, "chorus": 1, "midverse": 0}

books = a.books or edition.books("BSB")
args = SimpleNamespace(edition="BSB", style=None, profile=None, lead=None, max_lines=None, min_words=None, max_chars=None)
__import__("bible_song_builder.__main__").__main__.apply_layout_defaults(args)

# capture the stanzas/sections build_chapter makes
captured = {}
_orig_sections = render.sections
def _sections(sts, setting, sung, chorus=None):
    secs = _orig_sections(sts, setting, sung, chorus)
    captured["sts"], captured["secs"] = sts, secs
    return secs
render.sections = _sections
import bible_song_builder.__main__ as M  # noqa: E402
M.render.sections = _sections


def best_cuts(sizes, kinds, min_part=0, part_len=None):
    """sizes[i]: chars of section i (incl. separator). kinds[i]: kind of the boundary BEFORE section i.
    DP over cut positions: minimise (parts, -sum strength, max part)."""
    n = len(sizes)
    pre = [0]
    for s in sizes:
        pre.append(pre[-1] + s)
    INF = (10**9,)
    best = [INF] * (n + 1)      # best[j]: best score for sections[0:j] ending a part at j
    back = [None] * (n + 1)
    best[0] = (0, 0, 0)
    for j in range(1, n + 1):
        for i in range(j - 1, -1, -1):
            size = part_len(i, j)
            if size >= LIMIT and j - i > 1:
                break
            if best[i] == INF or (size < min_part and j < n or size < min_part and i > 0):
                continue
            if i > 0 and kinds[i] == "midverse":
                continue
            p, neg_str, mx = best[i]
            st = STRENGTH[kinds[i]] if i > 0 else 0
            cand = (p + 1, neg_str - st, max(mx, size))
            if cand < best[j]:
                best[j], back[j] = cand, i
    if best[n] == INF:
        return None
    cuts, j = [], n
    while j:
        i = back[j]
        cuts.append(i); j = i
    cuts = sorted(c for c in cuts if c)
    bounds = [0, *cuts, n]
    return cuts, [part_len(x, y) for x, y in zip(bounds, bounds[1:])]


rows, problems = [], []
kind_use = Counter()
for book in books:
    bt = edition.load_book("BSB", book)
    al = align.load("BSB", book, bt.file_hash, bt.chapter_fingerprints)
    plan.ensure(book)
    bp = plan.load_book(book)
    vmap = align.verse_map("BSB")
    speakers = lines.speaker_hits(bp["speakers"], al, bt, book, lambda b, cv: align.spine_to_edition(vmap, b, cv), align.lexeme_keys(book))
    prof = profiles.for_book("BSB", book)
    for c in sorted({c for c, _ in bt.verses}):
        res = build_chapter(book, c, "BSB", bt, al, bp, plan.load_chapter(book, c), speakers, vmap, args)
        ly = res["lyrics"]
        if len(ly) <= LIMIT:
            continue
        sts, secs = captured["sts"], captured["secs"]
        # section text sizes: re-render each section alone (voice tag re-emitted at its start)
        sizes, kinds, refs = [], [], []
        for k, s in enumerate(secs):
            _, part = render.render("", c, "", res["data"]["setting"], [s], [], prof, max_chars=10**9, layout=layout)
            sizes.append(len(part) + 1)
            first = s.stanza.lines[0]
            kinds.append("start" if k == 0 else s.kind)
            refs.append(f"{first.cv[0]}:{first.cv[1]}")
        memo = {}
        def part_len(i, j, secs=secs, setting=res["data"]["setting"]):
            # a part is pasted on its own: render its sections together, as Suno will get them
            if (i, j) not in memo:
                memo[i, j] = len(render.render("", c, "", setting, secs[i:j], [], prof, max_chars=10**9, layout=layout)[1])
            return memo[i, j]
        r = best_cuts(sizes, kinds, MIN_PART, part_len) or best_cuts(sizes, kinds, 0, part_len)
        if r is None:
            problems.append((book, c, len(ly), max(sizes)))
            continue
        cuts, parts = r
        for i in cuts:
            kind_use[kinds[i]] += 1
        rows.append((f"{book} {c}", len(ly), len(secs), parts, [(refs[i], kinds[i]) for i in cuts]))

print(f"limit {LIMIT}: {len(rows) + len(problems)} chapters over it")
print(f"cannot be cut at markers into parts < {LIMIT}: {len(problems)}", problems)
print("parts:", dict(sorted(Counter(len(r[3]) for r in rows).items())))
print("kinds of boundary used for cuts:", dict(kind_use))
print("largest part:", max(max(r[3]) for r in rows), " smallest part:", min(min(r[3]) for r in rows))
print()
for r in sorted(rows, key=lambda r: -r[1]):
    cut_s = ", ".join(f"{ref} ({k})" for ref, k in r[4])
    print(f"{r[0]:<9}{r[1]:>6}  {len(r[3])} parts {r[3]}  cut before {cut_s}")
