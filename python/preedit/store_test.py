import tempfile
import unittest
from pathlib import Path

from preedit import store


class StoreTest(unittest.TestCase):
    def test_save_load_and_remove_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sid = store.source_id(r"E:\Bruto\a.mp4", "longo")
            entry = {"id": sid, "format": "longo", "recording": r"E:\Bruto\a.mp4", "kind": "projeto"}
            store.save_source(root, entry, {"phrase": [{"x": [1.0], "y": 1}]})
            store.save_source(root, {**entry, "id": "outro", "format": "short"}, {"phrase": []})

            self.assertEqual([s["id"] for s in store.load_library(root)["sources"]], [sid, "outro"])
            self.assertEqual(store.load_examples(root, "longo"), [{"phrase": [{"x": [1.0], "y": 1}]}])
            self.assertEqual(store.remove_source(root, sid), "longo")
            self.assertEqual(store.load_examples(root, "longo"), [])
            self.assertIsNone(store.remove_source(root, "nao-existe"))

    def test_source_id_ignores_case_and_separates_formats(self):
        self.assertEqual(store.source_id(r"E:\Bruto\A.mp4", "longo"), store.source_id(r"e:\bruto\a.mp4", "longo"))
        self.assertNotEqual(store.source_id(r"E:\a.mp4", "longo"), store.source_id(r"E:\a.mp4", "short"))


if __name__ == "__main__":
    unittest.main()
