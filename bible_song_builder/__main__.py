"""bible-song-builder: build Suno lyrics for chapters of a book.

    python -m bible_song_builder RUT 1            # one chapter
    python -m bible_song_builder PSA 23 100       # several
    python -m bible_song_builder JON all          # the whole book
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, align, cast, castbuild, config, edition, fetch, lines, moods, plan, profiles, render, structure, textforms

ROOT = Path(__file__).resolve().parent.parent


def credits(bp: dict, ed: str, al: align.Alignment) -> list[str]:
    """The credit lines: the text and the alignment (pins.json), the structure (the plan's pins)."""
    p = fetch.pins()
    hf = p["huggingface"]
    sp = bp["pins"]
    lines_ds = bp["lines_dataset"]
    out = [
        f"Text: {ed}, {p['editions'][ed]['licence']}.",
        f"Structure: bcv-commons/{lines_ds} {sp[lines_ds]['tag']}, passage-facts {sp['passage-facts']['tag']}, "
        f"clause-connectives {sp['clause-connectives']['tag']} and clause-columns {sp['clause-columns']['tag']}, "
        "CC BY-SA 4.0 (bcv-commons; MACULA, Clear Bible / Biblica, CC BY 4.0; "
        "MAM, unfoldingWord ULT, UBS dictionaries, CC BY-SA 4.0).",
    ]
    if al.kind == "full":
        out.append(f"Alignment: bcv-commons/full-alignments-manual {hf['full-alignments-manual']['tag']}, "
                   f"layer {al.layer} (BSB translation tables, CC0).")
    elif al.kind == "compact":
        out.append(f"Alignment: bcv-commons/compact-alignments @{hf['compact-alignments']['revision'][:10]}, "
                   f"{al.layer}, CC0.")
    else:
        out.append("Alignment: none for this text; lines break at verse ends only.")
    return out


def chapter_credits(bp: dict, chapter: int, ed: str, al: align.Alignment,
                    mood: moods.Mood | None = None, section_moods: list | None = None) -> list[str]:
    out = credits(bp, ed, al)
    if chapter in al.chapters_off:
        out = [c if not c.startswith("Alignment:") else
               "Alignment: none for this chapter (the edition's text differs from the aligned text); "
               "lines break at verse ends only." for c in out]
    return out + [f"Mood: {c}" for c in moods.source_credits(mood, section_moods, bp["pins"], bp["sources"])]


def build_chapter(book: str, chapter: int, ed: str, bt: edition.BookText, al: align.Alignment,
                  bp: dict, cp: plan.ChapterPlan, speakers: dict, vmap: dict, args,
                  profile: profiles.Profile | None = None, mood: moods.Mood | None = None) -> dict:
    """Half 2 for one edition chapter: the book's plan ``bp`` and the chapter's ``cp`` (plan.py),
    projected onto the edition's text ``bt`` through the alignment ``al``."""
    profile = profile or profiles.for_book(ed, book, getattr(args, "profile", None), getattr(args, "lead", None))
    layout = config.layout(ed)
    to_ed = lambda cv: align.spine_to_edition(vmap, book, cv)  # noqa: E731
    ch_rows, facts = cp.rows, cp.facts
    marks = textforms.chapter_marks(facts, ch_rows, al, chapter, layout)
    lyric_lines = lines.build_lines(bt, chapter, ch_rows, al, speakers, to_ed, min_tokens=args.min_words,
                                    marks=marks, poetry=layout.get("lines", {}).get("poetry", "clauses+halves"),
                                    text_cfg=layout.get("text"))
    is_nt = bp["testament"] == "nt"
    sts = lines.stanzas(lyric_lines, bt, args.max_lines, cp.signals,
                        layout.get("stanzas", {}), is_nt)

    spine_verses = sorted({(r["chapter"], r["verse"]) for r in ch_rows})
    sv = structure.setting_verses(facts, spine_verses, layout.get("setting"))
    song = {e for e in map(to_ed, sv["song"]) if e and e[0] == chapter}
    poetic = {e for e in map(to_ed, sv["poetic"]) if e and e[0] == chapter}
    ch_verses = [(v.chapter, v.verse) for v in bt.chapter_verses(chapter)]
    n = max(len(ch_verses), 1)
    share = layout.get("setting", {}).get("share", 0.5)
    setting = ("song" if len(song) >= share * n else
               "poetry" if len(song | poetic) >= share * n else "prose")
    secs = render.sections(sts, setting, song | poetic, layout.get("chorus"))
    sec_moods = moods.section_moods(book, [s.stanza.verses for s in secs], cp.mood_facts, cp.model_moods,
                                    to_ed, profile)
    for s, m in zip(secs, sec_moods):
        s.mood = m

    notes = [f"Superscription before {c}:{v} (not sung): {t}" for (c, v), t in sorted(bt.titles.items()) if c == chapter]
    if layout.get("psalms", {}).get("heading_terms", True):
        if marks.heading_terms:
            desc = cp.labels
            notes.append("Heading terms (not sung): " + "; ".join(
                desc.get(code, code).removeprefix("heading: ").split(": a term of the text")[0]
                for code in marks.heading_terms))
        if marks.selah:
            notes.append("Selah at " + ", ".join(f"{c}:{v}" for c, v in sorted(marks.selah)))
    letter_names = config.language(fetch.pins()["editions"][ed]["iso"]).get("hebrew_letters", {})
    if marks.letters and not marks.acrostic_runs:
        # a letter per verse or line: too short for stanzas, so only noted
        notes.append("Acrostic (each unit starts with the next letter): " + ", ".join(
            f"{c}:{v} {x}" for ((c, v), _), x in marks.letters))

    if args.style:
        style, added = args.style, None
    else:
        style, added = moods.chapter_style(profile, mood)
    stem = f"{book}_{chapter:03d}"
    style_note = (f"Style: this chapter's own ({stem}.style.txt): {mood.mood or 'instruments'} (+ \"{added}\"), "
                  f"from {mood.basis}: {mood.evidence}" if added and mood else
                  f"Style: the book's ({book}.style.txt, profile {profile.name})"
                  + (f"; the source names {mood.evidence}, which sets no style in profile {profile.name}" if mood else ""))
    style_note += f". To change: config/books/{book}.toml, [chapters.{chapter}] (mood or style)"
    if args.style:
        style_note = "Style: given on the command line (--style)"

    notes_text, lyrics = render.render(bt.name, chapter, ed, setting, secs,
                                 chapter_credits(bp, chapter, ed, al, mood, sec_moods), profile, style=args.style,
                                 max_chars=args.max_chars, names=lambda sp: sp.label or cast.cast_name(sp.id),
                                 extra_notes=notes, layout=layout, letter_names=letter_names, style_note=style_note)
    data = {
        "book": book, "chapter": chapter, "edition": ed, "setting": setting,
        "profile": {"name": profile.name, "lead": profile.lead, "persona": profile.persona,
                    "style": profile.style, "tags": profile.tags},
        "style": style, "own_style": bool(added) or bool(args.style),
        "mood": ({"mood": mood.mood, "basis": mood.basis, "evidence": mood.evidence,
                  "instruments": list(mood.instruments)} if mood else None),
        "text_fingerprint": bt.fingerprint,
        "superscription": next((t for (c, _), t in sorted(bt.titles.items()) if c == chapter), None), "alignment": {"kind": al.kind, "layer": al.layer, "file": al.file},
        "pins": fetch.pins()["huggingface"], "bible-song-builder": __version__,
        "sections": [{
            "label": s.label, "sung": s.sung,
            "mood": ({"family": s.mood.family, "head": s.mood.head, "tag": s.mood.tag,
                      "evidence": s.mood.evidence, "model": s.mood.model} if s.mood else None),
            "verses": [f"{c}:{v}" for c, v in s.stanza.verses],
            "lines": [{"verse": f"{ln.cv[0]}:{ln.cv[1]}", "token": ln.first_token, "text": ln.text,
                       "quote": ln.quote,
                       "speaker": ({"id": ln.speaker.id, "label": ln.speaker.label, "voice": ln.speaker.voice}
                                   if ln.speaker else None),
                       "segment": ln.row_seg, "refrain": ln.refrain, "acrostic": ln.acrostic,
                       "selah": ln.selah} for ln in s.stanza.lines],
            "starts": s.kind,
        } for s in secs],
    }
    return {"notes": notes_text, "lyrics": lyrics, "style": style, "own_style": bool(added) or bool(args.style),
            "data": data}


def apply_layout_defaults(args) -> None:
    """Fill options not given on the command line from config/layout.toml."""
    lay = config.layout(getattr(args, "edition", None))
    for opt, (sec, key, default) in {"max_lines": ("stanzas", "max_lines", 12),
                                     "min_words": ("lines", "min_words", 3),
                                     "max_chars": ("length", "max_chars", 5000)}.items():
        if getattr(args, opt, None) is None:
            setattr(args, opt, lay.get(sec, {}).get(key, default))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bible-song-builder", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("book", help="USFM book code, e.g. RUT, PSA, LUK")
    ap.add_argument("chapters", nargs="+", help="chapter numbers, or 'all'")
    ap.add_argument("--edition", default="BSB", help="edition key in pins.json (default BSB)")
    ap.add_argument("--out", default=str(ROOT / "output"), help="output directory")
    ap.add_argument("--plans", default=str(plan.PLAN_DIR), help="song plan directory (written when missing or stale)")
    ap.add_argument("--style", help="override the style line")
    ap.add_argument("--profile", help="override the book's profile (config/books.toml) for this run")
    ap.add_argument("--lead", choices=["female", "male"], help="override the book's lead for this run")
    ap.add_argument("--max-lines", type=int, help="split stanzas longer than this (layout.toml stanzas.max_lines)")
    ap.add_argument("--min-words", type=int, help="join lines shorter than this (layout.toml lines.min_words)")
    ap.add_argument("--max-chars", type=int, help="flag lyrics longer than this (layout.toml length.max_chars)")
    ap.add_argument("--print", action="store_true", help="also print the result")
    ap.add_argument("--bare", action="store_true", help="write only the book and chapter files (no cast.csv, "
                                                        "README.txt), e.g. for examples/")
    args = ap.parse_args(argv)
    apply_layout_defaults(args)

    book = args.book.upper()
    castbuild.ensure(args.edition)
    bt = edition.load_book(args.edition, book)
    al = align.load(args.edition, book, bt.file_hash, bt.chapter_fingerprints)
    if al.kind != "full" or al.chapters_off:
        print(f"note: {book} text {bt.file_hash}: alignment = {al.kind} {al.file or ''}"
              + (f"; chapters whose text differs (verse-end breaks): {sorted(al.chapters_off)}" if al.chapters_off else ""),
              file=sys.stderr)
    plans = Path(args.plans)
    plan.ensure(book, plans)
    bp = plan.load_book(book, plans)
    speakers = lines.speaker_labels(bp["speakers"], al, bt)
    profile = profiles.for_book(args.edition, book, args.profile, args.lead)
    vmap = align.verse_map(args.edition)

    chapters = sorted({c for c, _ in bt.verses}) if args.chapters == ["all"] else [int(c) for c in args.chapters]
    to_ed = lambda cv: align.spine_to_edition(vmap, book, cv)  # noqa: E731
    book_moods = moods.apply_overrides(book, plan.edition_moods(bp, to_ed), profile)
    out_dir = Path(args.out) / book
    out_dir.mkdir(parents=True, exist_ok=True)
    write_book_files(out_dir, book, profile, book_moods, args)
    if not args.bare:
        castbuild.write_browse(Path(args.out))
        write_readme(Path(args.out))
    for c in chapters:
        res = build_chapter(book, c, args.edition, bt, al, bp, plan.load_chapter(book, c, plans), speakers, vmap,
                            args, profile, book_moods.get(c))
        stem = out_dir / f"{book}_{c:03d}"
        own = Path(f"{stem}.style.txt")
        if res["own_style"]:
            own.write_text(res["style"] + "\n", encoding="utf-8")
        elif own.exists():
            own.unlink()                     # left from an earlier run with other settings
        for old in (Path(f"{stem}.suno.txt"),):  # the one-file layout of earlier versions
            if old.exists():
                old.unlink()
        Path(f"{stem}.lyrics.txt").write_text(res["lyrics"], encoding="utf-8")
        Path(f"{stem}.notes.txt").write_text(res["notes"], encoding="utf-8")
        Path(f"{stem}.json").write_text(json.dumps(res["data"], ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{stem}.lyrics.txt  ({res['data']['setting']}, {profile.name}/{profile.lead}, "
              f"{'own style' if res['own_style'] else 'book style'}, {len(res['lyrics'])} chars)")
        if args.print:
            print(res["style"], "", res["lyrics"], sep="\n")
    return 0


def write_readme(out: Path) -> None:
    (out / "README.txt").write_text(
        "This folder is rebuilt by bible-song-builder: anything changed here is lost on the next run.\n\n"
        "To change the songs, edit the settings instead:\n"
        "  config/books/<BOOK>.toml   a book's profile and lead singer; a chapter's mood or style\n"
        "  config/profiles.toml       what each profile and each mood sounds like; the voice tags\n"
        "  config/cast.csv            a speaker's voice or name (look the speaker up in cast.csv here)\n"
        "  config/layout.toml         lines, stanzas, section tags, chorus, length\n\n"
        "Per chapter: paste <BOOK>_<CCC>.lyrics.txt into Suno's Lyrics box, and <BOOK>.style.txt\n"
        "(or <BOOK>_<CCC>.style.txt where there is one) into the Style of Music box.\n"
        "<BOOK>_<CCC>.notes.txt says which persona to pick and who sings what.\n", encoding="utf-8")


def write_book_files(out_dir: Path, book: str, profile: profiles.Profile, book_moods: dict, args) -> None:
    """<BOOK>.style.txt (the book's style line) and <BOOK>.notes.txt (which chapters have their own)."""
    style = args.style or profile.style
    (out_dir / f"{book}.style.txt").write_text(style + "\n", encoding="utf-8")
    own = []
    for c, m in sorted(book_moods.items()):
        _, added = moods.chapter_style(profile, m)
        if added and not args.style:
            own.append(f"{book} {c}: {m.mood or 'instruments'} (+ \"{added}\"), from {m.basis}: {m.evidence}")
    lines_out = [f"{book} · profile {profile.name}, {profile.lead} lead · settings: config/books/"
                 f"{book + '.toml' if (config.CONFIG / 'books' / f'{book}.toml').exists() else '_default.toml'}",
                 f"Style for every chapter: {book}.style.txt — except the chapters below, which have their own",
                 f"<chapter>.style.txt (the same style with a mood the Hebrew/Greek gives the chapter).", ""]
    lines_out += own or ["(no chapter of this book has its own style)"]
    (out_dir / f"{book}.notes.txt").write_text("\n".join(lines_out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
