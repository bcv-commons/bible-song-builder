"""End-to-end checks on real data (downloaded into cache/ on first run)."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bible_song_builder import align, cast, config, edition, lines, plan, profiles, structure  # noqa: E402
from bible_song_builder.__main__ import apply_layout_defaults, build_chapter  # noqa: E402


class Args:
    style = None
    profile = None
    lead = None
    max_lines = None
    min_words = None
    max_chars = None


def build(book, chapter):
    bt = edition.load_book("BSB", book)
    al = align.load("BSB", book, bt.file_hash, bt.chapter_fingerprints)
    plan.ensure(book)
    bp = plan.load_book(book)
    vmap = align.verse_map("BSB")
    sp = lines.speaker_hits(bp["speakers"], al, bt, book, lambda b, cv: align.spine_to_edition(vmap, b, cv), align.lexeme_keys(book))
    args = Args()
    apply_layout_defaults(args)
    res = build_chapter(book, chapter, "BSB", bt, al, bp, plan.load_chapter(book, chapter), sp,
                        align.verse_map("BSB"), args)
    return bt, al, res


def words(s):
    return re.findall(r"[^\W\d_]+", s)


class TestSpan(unittest.TestCase):
    def test_parse_span(self):
        self.assertEqual(align.parse_span("5"), [5])
        self.assertEqual(align.parse_span("5-7"), [5, 6, 7])
        self.assertEqual(align.parse_span("4,6"), [4, 6])
        self.assertEqual(align.parse_span("L3,1,2"), [3, 1, 2])
        self.assertEqual(align.parse_span("~"), [])


class TestRuth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bt, cls.al, cls.res = build("RUT", 1)

    def test_fingerprint_matches_alignment(self):
        self.assertEqual(self.bt.file_hash, "8b23cf7f")
        self.assertEqual(self.al.kind, "full")
        self.assertFalse(self.al.chapters_off)

    def test_lyrics_are_the_text_verbatim(self):
        """Every word of the chapter, in order, nothing added or dropped."""
        sung = [ln["text"] for s in self.res["data"]["sections"] for ln in s["lines"]]
        text = " ".join(v.text for v in self.bt.chapter_verses(1))
        self.assertEqual(words(" ".join(sung)), words(text))

    def test_voices(self):
        lyr = self.res["lyrics"]
        tags = set(re.findall(r"^\[[^\]]+\]$", lyr, re.M))
        self.assertIn("[Female Vocal]", tags)    # Naomi, Ruth
        self.assertIn("[Female Choir]", tags)    # the two daughters-in-law (1:10), the women (1:19)
        self.assertIn("[Bridge]", tags)          # Ruth 1:16-17, set as poetry
        self.assertFalse(any("Naomi" in t or "Ruth" in t for t in tags))   # tags never name a person
        self.assertIn("Naomi", self.res["notes"])         # names are in the comment block

    def test_profile_is_the_books(self):
        prof = profiles.for_book("BSB", "RUT")
        self.assertEqual(self.res["style"], prof.style)
        self.assertEqual(self.res["data"]["profile"]["name"], prof.name)

    def test_book_text_from_plain_data(self):
        """edition.book_text: the text as plain data (any source format), here one chapter, gives
        the chapter the same fingerprint, and the same speaker labels (they are chapter-local)."""
        one = edition.book_text("BSB", "RUT", {k: v.text for k, v in self.bt.verses.items() if k[0] == 1},
                                paragraph_starts={cv for cv in self.bt.paragraph_starts if cv[0] == 1},
                                name=self.bt.name)
        self.assertEqual(one.chapter_fingerprints[1], self.bt.chapter_fingerprints[1])
        self.assertEqual(one.paragraph_starts, {cv for cv in self.bt.paragraph_starts if cv[0] == 1})
        self.assertEqual(len(one.chapter_verses(1)), 22)
        refs = plan.load_book("RUT")["speakers"]
        lex = align.lexeme_keys("RUT")
        labels = lambda bt: {s: (p.label, p.pointer) for s, p in lines.speaker_labels(  # noqa: E731
            lines.speaker_hits(refs, self.al, bt, "RUT", lexemes=lex), 1).items()}
        whole, alone = labels(self.bt), labels(one)
        # the women of 1:19 are named only in 4:14: with chapter 1 alone, no label but the pointer
        sid, (label, pointer) = next((s, lp) for s, lp in alone.items() if lp[1])
        self.assertIsNone(label)
        self.assertEqual((pointer["book"], pointer["verse"], pointer["strong"]), ("RUT", "4:14", ["H802"]))
        self.assertIsNotNone(whole[sid][0])
        with_4 = edition.book_text("BSB", "RUT", {k: v.text for k, v in self.bt.verses.items() if k[0] in (1, 4)})
        self.assertEqual(labels(with_4)[sid], whole[sid])
        # a partial text: found by its chapter fingerprints alone
        part = edition.book_text("BSB", "RUT", {k: v.text for k, v in self.bt.verses.items() if k[0] == 1}, partial=True)
        al = align.load("BSB", "RUT", part.file_hash, part.chapter_fingerprints, partial=part.partial)
        self.assertNotEqual(al.kind, "none")
        self.assertNotIn(1, al.chapters_off)

    def test_reordered_clauses_get_own_lines(self):
        v6 = [ln["text"] for s in self.res["data"]["sections"] for ln in s["lines"] if ln["verse"] == "1:6"]
        self.assertEqual(v6[0], "When Naomi heard in Moab")
        self.assertIn("by providing them with food,", v6)


class TestCompact(unittest.TestCase):
    def test_pull_unaligned(self):
        """With a compact alignment (content words only), a line starts at the clause's unlinked
        words before its first linked word: "when the judges ruled", not "when the | judges"."""
        from bible_song_builder import fetch
        ed = fetch.pins()["editions"]["BSB"]
        layer = ed["full_layer"]
        ed["full_layer"] = None
        try:
            bt, al, res = build("RUT", 1)
        finally:
            ed["full_layer"] = layer
        self.assertEqual(al.kind, "compact")
        self.assertIn("\nwhen the judges ruled,\nthere was a famine in the land.\n", res["lyrics"])


class TestCast(unittest.TestCase):
    def test_rules(self):
        def info(lemma, name="", members=False, quotes=0, divine=0):
            i = cast.SpeakerInfo(members=members, quotes=quotes, divine=divine)
            if lemma:
                i.lemmas[lemma] += 1
            if name:
                i.names[name] += 1
            return i
        rules = config.cast_rules()
        self.assertEqual(cast.rule_voice(info("אִשָּׁה"), rules)[0], "female")
        self.assertEqual(cast.rule_voice(info("אִשָּׁה אָדוֹן"), rules)[0], "female")     # master's wife
        self.assertEqual(cast.rule_voice(info("אָב נַעֲרָה"), rules)[0], "male")          # the girl's father
        self.assertEqual(cast.rule_voice(info("רָחֵל, לֵאָה"), rules)[0], "female_group")
        self.assertEqual(cast.rule_voice(info("אָב, אֵם"), rules)[0], "group")
        self.assertEqual(cast.rule_voice(info("θεός", quotes=10, divine=10), rules)[0], "divine")
        self.assertEqual(cast.voice_of(None, None), rules["unknown"])

    def test_speaking_verb(self):
        """Hebrew verb gender and number name the voice: Acsah "she said", the Hivites "they said"."""
        table = config.cast_table()
        self.assertEqual(table["c0134"]["voice"], "female")     # Acsah, JOS 15:19
        self.assertEqual(table["c0130"]["voice"], "group")      # the Hivites, JOS 9
        # a Greek participle agrees with its noun, not a person: "a voice saying" stays male (default)
        self.assertNotEqual(table["n0364"]["voice"], "female")

    def test_nested_quote_sung_by_outer_speaker(self):
        _, _, res = build("GEN", 3)
        lyr = res["lyrics"].split("\n")
        i = lyr.index("God has said,")
        self.assertFalse(lyr[i + 1].startswith("["))     # Eve goes on singing God's words


class TestTextForms(unittest.TestCase):
    """passage-facts v0.2: refrains, acrostics, couplet halves, psalm headings."""

    def test_refrain_is_the_chorus(self):
        _, _, res = build("GEN", 1)
        ch = [s for s in res["data"]["sections"] if s["label"] == "Chorus"]
        evening = [s for s in ch if any(ln["text"].startswith("And there was evening") for ln in s["lines"])]
        self.assertEqual(len(evening), 6)               # evening and morning, days 1-6
        saw = [s for s in ch if s["lines"][0]["text"] == "And God saw"]
        self.assertGreaterEqual(len(saw), 2)            # "And God saw that it was good" (the text's own refrain too)
        self.assertNotIn("Then God said,", [ln["text"] for s in ch for ln in s["lines"]])

    def test_speech_frame_is_no_chorus(self):
        """John 1: "καὶ λέγει αὐτῷ" (passage-facts calls it a refrain, 1:41, 45, 51) introduces a
        quote each time: no chorus. 1:32: the quote starts inside the source's clause line
        ("ὅτι Τεθέαμαι"): "I saw" is John's (plan.split_at_quote_starts). With the compact
        alignment, as for most editions."""
        from bible_song_builder import fetch
        ed = fetch.pins()["editions"]["BSB"]
        layer = ed["full_layer"]
        ed["full_layer"] = None
        try:
            _, _, res = build("JHN", 1)
        finally:
            ed["full_layer"] = layer
        self.assertNotIn("Chorus", [s["label"] for s in res["data"]["sections"]])
        ls = [ln for s in res["data"]["sections"] for ln in s["lines"]]
        saw = next(ln for ln in ls if ln["verse"] == "1:32" and "I saw" in ln["text"])
        self.assertTrue(saw["text"].startswith("“I saw"))
        self.assertIsNotNone(saw["speaker"])

    def test_acrostic_letters_start_stanzas(self):
        _, _, res = build("PSA", 119)
        starts = [s["verses"][0] for s in res["data"]["sections"] if any(ln["acrostic"] for ln in s["lines"])]
        self.assertEqual(len(starts), 22)
        self.assertEqual(starts[:3], ["119:1", "119:9", "119:17"])
        self.assertIn("ב Beth", res["notes"])

    def test_heading_terms_and_selah_noted(self):
        _, _, res = build("PSA", 3)
        self.assertIn("Heading terms (not sung): a psalm", res["notes"])
        self.assertIn("Selah at 3:2, 3:4, 3:8", res["notes"])

    def test_half_b_starts_a_line(self):
        _, _, res = build("PSA", 23)
        texts = [ln["text"] for s in res["data"]["sections"] for ln in s["lines"]]
        self.assertIn("He guides me in the paths of righteousness for the sake of His name.", texts)

    def test_section_tag_modes(self):
        from bible_song_builder import render
        self.assertEqual(render.section_tag("Verse 3"), "[Verse 3]")
        self.assertEqual(render.section_tag("Verse 3", number_verses=False), "[Verse]")
        self.assertIsNone(render.section_tag("Verse 3", "chorus_bridge"))
        self.assertEqual(render.section_tag("Chorus", "chorus_bridge"), "[Chorus]")
        self.assertIsNone(render.section_tag("Chorus", "none"))


class TestMoods(unittest.TestCase):
    def moods_of(self, book):
        from bible_song_builder import align, moods
        vmap = align.verse_map("BSB")
        return moods.book_moods(book, structure.passage_facts(book), structure.clause_lines(book, set(range(200))),
                                lambda cv: align.spine_to_edition(vmap, book, cv), config.layout("BSB"))

    def test_span_section_moods(self):
        """moods.span_section_moods: a line takes the shortest span over it (per pass); a mood
        change over the song's limit is dropped, and the mood before it goes on."""
        from bible_song_builder import moods
        rows = [{"words": [f"w{i}"]} for i in range(8)]

        def span(s, p, a, b, mood, strength=2, agree=True):
            return {"s": s, "pass": p, "mood": mood, "strength": strength, "agree": agree, "first": f"w{a}",
                    "last": f"w{b}", "verses": [[1, a + 1, b + 1]], "because": ""}
        spans = [span(0, "a", 0, 7, "shalom"), span(1, "a", 2, 3, "evel", 3), span(2, "b", 0, 7, "shalom"),
                 span(3, "b", 2, 3, "evel", 3)]
        prof = profiles.for_book("BSB", "RUT")
        secs = [[(rows[0], 10), (rows[1], 10)], [(rows[2], 10), (rows[3], 10)], [(rows[4], 10), (rows[5], 10)]]
        got = moods.span_section_moods("RUT", secs, rows, spans, prof)
        # 60 words: 2 changes at most, so the weaker one back to shalom is dropped (evel goes on)
        self.assertEqual([m.mood if m else None for m in got], ["shalom", "evel", None])
        long = [[(r, 100)] for r in rows[:6]]                                                    # 600 words: 6
        self.assertEqual([m.mood if m else None for m in moods.span_section_moods("RUT", long, rows, spans, prof)],
                         ["shalom", "shalom", "evel", "evel", "shalom", "shalom"])
        self.assertIsNone(moods.span_section_moods("RUT", secs, rows, [], prof))               # no spans: fall back

    def test_span_moods_by_family(self):
        """A section's share is counted by family (rinnah and simchah are both joy), and a section
        with no clear mood goes on in the one before only where that still holds keep_share of it
        (Psalm 22: "desperate" does not run on into the praise)."""
        from bible_song_builder import moods
        order = (["tsarah"] * 2 + ["rinnah", "rinnah", "simchah", "yirah", "yirah"]
                 + ["rinnah", "rinnah", "mivtach", "mivtach", "mivtach", "tsarah", "tsarah", "yirah"]
                 + ["mivtach"] * 3 + ["tsarah"] * 2 + ["yirah"] * 2)
        rows = [{"words": [f"w{i}"]} for i in range(len(order))]
        spans = [{"s": 2 * i + j, "pass": p, "mood": m, "strength": 2, "agree": True, "first": f"w{i}",
                  "last": f"w{i}", "verses": [[1, i + 1, i + 1]], "because": ""}
                 for i, m in enumerate(order) for j, p in enumerate("ab")]
        cuts = [0, 2, 7, 15, len(order)]
        secs = [[(r, 100) for r in rows[a:b]] for a, b in zip(cuts, cuts[1:])]
        got = moods.span_section_moods("PSA", secs, rows, spans, profiles.for_book("BSB", "PSA"))
        # joy 3/5 (rinnah 2/5 alone); then joy keeps 2/8 (no family has half): it goes on;
        # then joy has nothing left: trust, the family with the most
        self.assertEqual([m.mood if m else None for m in got], ["tsarah", "rinnah", None, "mivtach"])

    def test_reading_fills_chapter_mood(self):
        """The chapter reading gives Ruth 1 its mood (no source cue); a psalm keeps its heading's."""
        from bible_song_builder import align, moods
        vmap = align.verse_map("BSB")
        to_ed = lambda cv: align.spine_to_edition(vmap, "RUT", cv)  # noqa: E731
        bp = plan.load_book("RUT")
        got = moods.with_readings(plan.edition_moods(bp, to_ed), bp["readings"], to_ed)
        self.assertEqual((got[1].mood, got[1].basis), ("evel", "reading"))
        self.assertIn("passage-mood-spans-model", got[1].evidence)
        psa = plan.load_book("PSA")
        to_p = lambda cv: align.spine_to_edition(vmap, "PSA", cv)  # noqa: E731
        self.assertEqual(moods.with_readings(plan.edition_moods(psa, to_p), psa["readings"], to_p)[136].mood, "praise")

    def test_heading_moods(self):
        m = self.moods_of("PSA")
        self.assertEqual(m[17].mood, "prayer")          # תְּפִלָּה
        self.assertEqual(m[150].mood, "praise")         # הַלְלוּ יָהּ
        self.assertEqual(m[4].instruments, ("strings",))
        self.assertEqual(m[121].mood, "pilgrimage")     # שִׁיר הַמַּעֲלוֹת
        self.assertEqual((m[23].mood, m[23].basis), ("trust", "type"))   # Tyndale: mivtach
        self.assertEqual(m[119].basis, "commentary")    # Tyndale names five types: none clearly; the commentators: prayer

    def test_commentary_moods(self):
        from bible_song_builder import moods
        self.assertEqual(moods.commentary_mood("וּמִתְפַּלֵּל", {"תפל": "prayer"}), "prayer")
        m = self.moods_of("PSA")[51]
        self.assertEqual((m.mood, m.basis), ("prayer", "commentary"))   # Meiri: לתפלה

    def test_section_moods(self):
        from bible_song_builder import moods
        prof = profiles.for_book("BSB", "PSA")
        vmap = __import__("bible_song_builder.align", fromlist=["x"]).verse_map("BSB")
        to_ed = lambda cv: __import__("bible_song_builder.align", fromlist=["x"]).spine_to_edition(vmap, "PSA", cv)
        spine = sorted({(r["chapter"], r["verse"]) for r in structure.clause_lines("PSA", {22})})
        sm = moods.section_moods("PSA", [[(22, v) for v in range(23, 26)], [(22, 1)]],
                                 *moods.mood_spans("PSA", structure.passage_facts("PSA"), spine,
                                                  structure.clause_lines("PSA", {22})), to_ed, prof)
        self.assertEqual(sm[0].family, "md.samach")                     # 22:23-25 praise in the assembly
        self.assertEqual((sm[0].mood, sm[0].tag), ("simchah", "[Mood: joyful]"))   # by mood-list.toml

    def test_family_words(self):
        """The edition's word for a mood family: its rendering of the noun naming the family's mood."""
        from bible_song_builder import moods
        bt = edition.load_book("BSB", "PSA")
        al = align.load("BSB", "PSA", bt.file_hash, bt.chapter_fingerprints)
        w = moods.family_words(align.lexeme_keys("PSA"), al, bt, "ot")
        self.assertEqual((w["simchah"], w["tsarah"], w["sinah"]), ("joy", "trouble", "hatred"))
        bt = edition.load_book("BSB", "LUK")
        al = align.load("BSB", "LUK", bt.file_hash, bt.chapter_fingerprints)
        self.assertEqual(moods.family_words(align.lexeme_keys("LUK"), al, bt, "nt")["simchah"], "joy")

    def test_heading_words(self):
        """Where the alignment covers a psalm heading, its terms are named in the edition's words.
        The BSB's does not (the title is not verse text), so an alignment that does is made up:
        למנצח on the first two words of 22:1 ("My" is an edge word, trimmed)."""
        import copy
        bt, al, res = build("PSA", 22)
        self.assertIn("Heading terms (not sung): for the leader (למנצח)", res["notes"])
        al2 = copy.copy(al)
        al2.links = {**al.links, "190220010011": ((22, 1), {0}), "190220010012": ((22, 1), {1})}
        sp = lines.speaker_hits(plan.load_book("PSA")["speakers"], al2, bt)
        args = Args()
        apply_layout_defaults(args)
        res2 = build_chapter("PSA", 22, "BSB", bt, al2, plan.load_book("PSA"), plan.load_chapter("PSA", 22), sp,
                             align.verse_map("BSB"), args)
        self.assertIn("Heading terms (not sung): God (למנצח);", res2["notes"])

    def test_song_in_narrative(self):
        self.assertEqual(self.moods_of("EXO")[15].mood, "song")
        self.assertNotIn(12, self.moods_of("JOS"))      # a list of kings in song layout

    def test_style_files(self):
        from bible_song_builder import moods
        prof = profiles.for_book("BSB", "PSA")
        style, added = moods.chapter_style(prof, self.moods_of("PSA")[17])
        self.assertTrue(style.startswith(prof.base_style + ", ") and added)
        self.assertEqual(moods.chapter_style(prof, None), (prof.style, None))


class TestExamples(unittest.TestCase):
    def test_examples_current(self):
        """examples/ is what the code and config build now (make examples to refresh it)."""
        import contextlib
        import io
        import tempfile
        from bible_song_builder.__main__ import main
        ex = ROOT / "examples"
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            for b, c in (("RUT", 1), ("PSA", 22), ("PSA", 23), ("PSA", 136), ("EXO", 15), ("EXO", 39), ("LUK", 1)):
                main([b, str(c), "--out", tmp, "--bare"])
            got = {p.relative_to(tmp): p.read_bytes() for p in Path(tmp).rglob("*") if p.is_file()}
        want = {p.relative_to(ex): p.read_bytes() for p in ex.rglob("*") if p.is_file()}
        self.assertEqual(sorted(got), sorted(want), "files differ: run make examples")
        stale = [str(k) for k in got if got[k] != want[k]]
        self.assertEqual(stale, [], "examples/ is out of date: run make examples")


class TestConfig(unittest.TestCase):
    def test_layers(self):
        self.assertEqual(config.merge({"a": {"x": 1, "y": 2}}, {"a": {"y": 3}}), {"a": {"x": 1, "y": 3}})
        self.assertIn("text", config.layout("BSB"))

    def test_line_start_by_spacing(self):
        """layout.toml [text] line_start "spacing": a line takes the marks touching its first word,
        and an opening mark standing alone; a closing mark, a dash and clause ends stay behind. The
        same rule in every language."""
        cases = [("och sade till honom: ”Vi har", "Vi", "”Vi har"), ("Messias” - det", "det", "det"),
                 ("dit : « Nous", "Nous", "« Nous"), ("Nous » dit-il", "dit", "dit-il"),
                 ("said, “I saw", "I", "“I saw"), ("said.” Then", "Then", "Then"), ("dijo: ¿Qué", "Qué", "¿Qué"),
                 ("他說：「我們", "我", "「我們"), ("Und er sprach: „Kommt", "Kommt", "„Kommt"),
                 ("You — majestic", "majestic", "majestic")]
        rule = lines.line_start_rule({})
        for text, word, line in cases:
            self.assertEqual(text[lines._cut_start(text, text.rindex(word), rule):], line)
        self.assertEqual(lines.line_start_rule({"line_start": "list"})[0], "list")

    def test_stray_link_inside_a_quote(self):
        """lines._strays: a short piece in another voice inside a quote goes back to the quote when a
        stray link put it there (out of source order, no punctuation around it), not when the
        narrator's words are set off ("“Look,” said Naomi, “your …")."""
        def ln(text, quote, seg):
            return lines.LyricLine((1, 15), text, 0, quote, None, seg, row={"seg": seg})
        stray = [ln("”Det var", "q", 39), ln("om", None, 38), ln("honom jag sade:", "q", 40)]
        self.assertEqual([x.quote for x in lines._strays(stray, 3)], ["q", "q", "q"])
        said = [ln("“Look,”", "q", 39), ln("said Naomi,", None, 38), ln("“your sister-in-law", "q", 40)]
        self.assertEqual([x.quote for x in lines._strays(said, 3)], ["q", None, "q"])
        in_order = [ln("Det var", "q", 39), ln("om", None, 40), ln("honom", "q", 41)]
        self.assertEqual([x.quote for x in lines._strays(in_order, 3)], ["q", None, "q"])

    def test_split_at_quote_starts(self):
        rows = [{"chapter": 1, "verse": 1, "seg": 1, "words": ["a", "b"], "clause_key": "a", "para_end": True},
                {"chapter": 1, "verse": 1, "seg": 2, "words": ["c"], "quotation": "b", "speaker_id": "n1", "clause_key": "c"}]
        got = plan.split_at_quote_starts(rows)
        self.assertEqual([(r["words"], r.get("quotation"), r.get("speaker_id"), r.get("clause_key"), r.get("para_end"))
                          for r in got], [(["a"], None, None, "a", None), (["b"], "b", "n1", None, True),
                                          (["c"], "b", "n1", "c", None)])

    def test_count_units(self):
        self.assertEqual(lines.count_units("In the beginning, God"), 4)
        self.assertEqual(lines.count_units("起初，神创造天地。", "characters"), 7)

    def test_stanzas_split_at_source_breaks(self):
        _, _, res = build("MRK", 1)
        starts = [s["verses"][0] for s in res["data"]["sections"]]
        self.assertIn("1:9", starts)       # Καὶ ἐγένετο ἐν ἐκείναις ταῖς ἡμέραις: a new episode


class TestPlan(unittest.TestCase):
    """The song plan (half 1) holds no edition: the same plan for every edition."""

    def test_plan_is_edition_free(self):
        plan.ensure("RUT")
        bp = plan.load_book("RUT")
        cp = plan.load_chapter("RUT", 1)
        json_text = (ROOT / "plan" / "RUT" / "RUT_001.json").read_text(encoding="utf-8")
        self.assertNotIn("Naomi", json_text + (ROOT / "plan" / "RUT" / "RUT.json").read_text(encoding="utf-8"))
        self.assertEqual(bp["schema"], plan.SCHEMA)
        self.assertEqual({r["chapter"] for r in cp.rows}, {1, 2})          # RUT has no chapter 0
        self.assertTrue(all("words" in r for r in cp.rows))
        self.assertIn('"rows"', json_text)

    def test_spine_chapters(self):
        """An edition chapter reads every spine chapter a verse comes from, also two chapters away
        (the Vulgate and Russian Synodal Psalms: spine PSA 115:1 is their PSA 113:9)."""
        vmap = {"PSA 115:1": "PSA 113:9", "PSA 114:1": "PSA 113:1", "GEN 9:1": "PSA 113:2"}
        self.assertEqual(align.spine_chapters(vmap, "PSA", 113), [112, 113, 114, 115])
        self.assertEqual(align.spine_chapters({}, "RUT", 1), [1, 2])

    def test_runs(self):
        from bible_song_builder import moods
        vs = [(1, 1), (1, 2), (1, 3), (1, 5), (2, 1)]
        self.assertEqual(moods.runs(vs), [[1, 1, 3], [1, 5, 5], [2, 1, 1]])
        self.assertEqual(moods.unrun(moods.runs(vs)), vs)


class TestPsalm(unittest.TestCase):
    def test_superscription_kept_out_of_verse(self):
        bt, al, res = build("PSA", 23)
        self.assertEqual(bt.file_hash, "c867de4b")
        self.assertEqual(al.kind, "full")
        self.assertEqual(res["data"]["setting"], "poetry")
        sung = [ln for ln in res["lyrics"].split("\n") if ln and not ln.startswith("[")]
        self.assertTrue(sung[0].startswith("The LORD is my shepherd"))
        self.assertIn("A Psalm of David.", res["notes"])   # in the comment block


if __name__ == "__main__":
    unittest.main()
