import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import style_store


def entry(video_id: str, profile: str, **extra) -> dict:
    return {"id": video_id, "profile": profile, "name": f"{video_id}.mp4", **extra}


class StyleStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Path(self._tmp.name) / "subtitle-style"

    def tearDown(self):
        self._tmp.cleanup()

    def test_empty_store_has_empty_library(self):
        self.assertEqual(style_store.load_library(self.store), {"version": 1, "videos": []})
        self.assertEqual(style_store.load_profile_examples(self.store, "vertical"), [])

    def test_saves_videos_and_loads_examples_by_profile(self):
        style_store.save_video(self.store, entry("a", "vertical"), {"gaps": [1]})
        style_store.save_video(self.store, entry("b", "horizontal"), {"gaps": [2]})
        style_store.save_video(self.store, entry("c", "vertical"), {"gaps": [3]})

        self.assertEqual(style_store.load_profile_examples(self.store, "vertical"), [{"gaps": [1]}, {"gaps": [3]}])
        self.assertEqual([video["id"] for video in style_store.load_library(self.store)["videos"]], ["a", "b", "c"])
        self.assertIsInstance(style_store.load_library(self.store)["videos"][0]["taughtAt"], int)

    def test_teaching_the_same_video_again_replaces_it(self):
        style_store.save_video(self.store, entry("a", "vertical", f1Formula=0.5), {"gaps": [1]})
        style_store.save_video(self.store, entry("a", "vertical", f1Formula=0.7), {"gaps": [9]})

        videos = style_store.load_library(self.store)["videos"]
        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]["f1Formula"], 0.7)
        self.assertEqual(style_store.load_profile_examples(self.store, "vertical"), [{"gaps": [9]}])

    def test_remove_video_returns_its_profile_and_deletes_examples(self):
        style_store.save_video(self.store, entry("a", "horizontal"), {"gaps": [1]})

        self.assertEqual(style_store.remove_video(self.store, "a"), "horizontal")
        self.assertEqual(style_store.load_library(self.store)["videos"], [])
        self.assertFalse((self.store / "examples" / "a.json").exists())
        self.assertIsNone(style_store.remove_video(self.store, "a"))

    def test_word_fixes_accumulate(self):
        style_store.add_word_fixes(self.store, [("kareka", "Careca")])
        style_store.add_word_fixes(self.store, [("kareka", "Careca"), ("mano", "Mano")])
        style_store.add_word_fixes(self.store, [])

        counts = json.loads((self.store / "word_fixes.json").read_text(encoding="utf-8"))
        self.assertEqual(counts, {"kareka->Careca": 2, "mano->Mano": 1})

    def test_video_id_is_stable_for_the_same_path(self):
        first = style_store.video_id_for("D:\\videos\\Aula.mp4")
        self.assertEqual(first, style_store.video_id_for("d:\\videos\\aula.mp4"))
        self.assertNotEqual(first, style_store.video_id_for("D:\\videos\\outra.mp4"))
        self.assertEqual(len(first), 12)


if __name__ == "__main__":
    unittest.main()
