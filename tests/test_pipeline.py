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
    sp = lines.speaker_labels(bp["speakers"], al, bt)
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

    def test_reordered_clauses_get_own_lines(self):
        v6 = [ln["text"] for s in self.res["data"]["sections"] for ln in s["lines"] if ln["verse"] == "1:6"]
        self.assertEqual(v6[0], "When Naomi heard in Moab")
        self.assertIn("by providing them with food,", v6)


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
                                 *moods.mood_spans("PSA", structure.passage_facts("PSA"), spine), to_ed, prof)
        self.assertEqual(sm[0].family, "md.samach")                     # 22:23-25 praise in the assembly
        self.assertEqual(sm[0].tag, "[Mood: joyful]")

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
