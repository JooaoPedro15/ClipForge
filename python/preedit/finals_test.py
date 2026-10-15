import tempfile
import unittest
from pathlib import Path

from premiere_project import SequenceEdit

from preedit.finals import Candidate, name_key, pair_videos, scan_videos


def candidate(name, duration, export=None, project="p.prproj", modified=1.0):
    return Candidate(project, SequenceEdit(name, False, [], duration, export), modified)


def folder(*paths):
    files = {}
    for path in paths:
        files.setdefault(name_key(path), []).append(Path(path))
    return files


class PairTest(unittest.TestCase):
    def test_pairs_by_the_exported_file_and_its_range(self):
        # Nome com maiuscula e acento composto no projeto, minuscula e acento decomposto no disco.
        sequence = candidate("Sequência 08", 163.33, (r"C:\Users\Joao\Desktop\É Eu Sou um Robo.mp4", 25.0, 50.325))
        on_disk = "D:/Finais/sub/e\u0301 eu sou um robo.mp4"

        (pair,), skipped, without = pair_videos([sequence], folder(on_disk), {str(Path(on_disk)): 25.36}.get)

        self.assertEqual((pair.video, pair.start, pair.end), (str(Path(on_disk)), 25.0, 50.325))
        self.assertEqual((skipped, without), ([], 0))

    def test_whole_sequence_export_with_an_old_range(self):
        sequence = candidate("Inteira", 60.0, (r"D:\Prontos\inteira.mp4", 5.0, 20.0))

        (pair,), _, _ = pair_videos([sequence], folder("D:/Finais/inteira.mp4"), lambda path: 60.0)

        self.assertEqual((pair.start, pair.end), (0.0, 60.0))

    def test_missing_file_and_wrong_duration_are_reported(self):
        sequences = [candidate("S1", 100.0, (r"D:\Prontos\sumiu.mp4", 0.0, 30.0)), candidate("S2", 100.0, (r"D:\Prontos\curto.mp4", 0.0, 10.0))]

        pairs, skipped, _ = pair_videos(sequences, folder("D:/Finais/curto.mp4"), lambda path: 30.0)

        self.assertEqual(pairs, [])
        self.assertEqual(
            skipped,
            [
                {"recording": "sumiu.mp4", "reason": "video exportado nao encontrado na pasta (S1)"},
                {"recording": str(Path("D:/Finais/curto.mp4")), "reason": "o video nao tem a duracao do trecho exportado (S2)"},
            ],
        )

    def test_same_export_in_two_versions_counts_once_and_the_oldest_wins(self):
        export = (r"D:\Prontos\a.mp4", 0.0, 30.0)
        old = candidate("S", 100.0, export, project="velho.prproj", modified=1.0)
        new = candidate("S", 100.0, export, project="novo.prproj", modified=2.0)
        earlier_short = candidate("S", 90.0, (r"D:\Prontos\b.mp4", 40.0, 60.0), project="mais-velho.prproj", modified=0.5)
        durations = {str(Path("D:/Finais/a.mp4")): 30.0, str(Path("D:/Finais/b.mp4")): 20.0}

        pairs, skipped, _ = pair_videos([new, old, earlier_short], folder("D:/Finais/a.mp4", "D:/Finais/b.mp4"), durations.get)

        self.assertEqual(skipped, [])
        self.assertEqual([(p.project, Path(p.video).name) for p in pairs], [("velho.prproj", "a.mp4"), ("mais-velho.prproj", "b.mp4")])

    def test_two_exports_to_the_same_file_are_ambiguous(self):
        sequences = [candidate("A", 100.0, (r"D:\Prontos\mesmo.mp4", 0.0, 30.0)), candidate("B", 80.0, (r"D:\Prontos\mesmo.mp4", 10.0, 40.0))]

        pairs, skipped, _ = pair_videos(sequences, folder("D:/Finais/mesmo.mp4"), lambda path: 30.0)

        self.assertEqual(pairs, [])
        self.assertEqual([item["reason"] for item in skipped], ["mais de uma exportacao para o mesmo arquivo (A, B)"])

    def test_sequences_without_export_are_only_counted(self):
        pairs, skipped, without = pair_videos([candidate("A", 10.0), candidate("B", 20.0)], {}, lambda path: 0.0)

        self.assertEqual((pairs, skipped, without), ([], [], 2))


class ScanTest(unittest.TestCase):
    def test_indexes_videos_by_name_in_subfolders_and_skips_app_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Bilibili").mkdir()
            for name in ("a.mp4", "Bilibili/B.MOV", "Bilibili/b.hardsub.zh.mp4", "notas.txt", "Bilibili/a.mp4"):
                (root / name).write_bytes(b"x")

            files = scan_videos(root)

            self.assertEqual(sorted(files), ["a.mp4", "b.mov"])
            self.assertEqual([path.relative_to(root).as_posix() for path in files["a.mp4"]], ["Bilibili/a.mp4", "a.mp4"])


if __name__ == "__main__":
    unittest.main()
