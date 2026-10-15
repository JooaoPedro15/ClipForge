import unittest

from premiere_project import ClipEdit, SequenceEdit

from preedit.project_labels import collect_labels, final_labels, labels_from_sequences, merge_ranges
from preedit.types import Range, Zoom

BRUTO = r"E:\Bruto\2026-10-05 14-50-31.mp4"
FINAL = r"D:\Finais\video pronto.mp4"


def clip(track, start, end, source_in, scale=100.0, source=BRUTO, speed=1.0):
    return ClipEdit(track, start, end, source, source_in, round(source_in + (end - start) * speed, 3), scale)


class LabelsTest(unittest.TestCase):
    def test_short_keeps_every_track_and_zooms_come_from_the_zoom_track(self):
        # V1: recorte com zooms de corte; V2: a mesma gravacao reduzida no topo, com um trecho so dela em 100%
        # (troca de layout, nao zoom: a trilha do zoom e a que tem mais zooms).
        v1 = [clip(1, 0.0, 3.5, 71.91), clip(1, 3.5, 4.5, 93.93, scale=170.0), clip(1, 4.5, 6.0, 96.4), clip(1, 6.0, 6.8, 97.9, scale=140.0)]
        v2 = [clip(2, 0.0, 3.5, 71.91, 62.7), clip(2, 6.8, 7.8, 130.0, 100.0)]
        (labels,) = labels_from_sequences([SequenceEdit("Sequência 41", True, v1 + v2)])

        self.assertEqual(labels.format, "short")
        self.assertEqual(labels.kept, [Range(71.91, 75.41), Range(93.93, 94.93), Range(96.4, 98.7), Range(130.0, 131.0)])
        self.assertEqual(labels.zooms, [Zoom(93.93, 94.93, 1.7), Zoom(97.9, 98.7, 1.4)])
        self.assertEqual(labels.span, Range(71.91, 131.0))
        self.assertFalse(labels.preedited)

    def test_copies_merge_and_long_videos_have_no_zoom(self):
        first = [clip(1, 0.0, 10.0, 0.0), clip(1, 10.0, 20.0, 30.0)]
        compilation = [clip(1, 0.0, 10.0, 0.0), clip(1, 10.0, 15.0, 50.0)]  # copia do primeiro trecho + outro
        result = labels_from_sequences([SequenceEdit("Longo", False, first), SequenceEdit("Compilacao", False, compilation)])

        (labels,) = result
        kept = [Range(0.0, 10.0), Range(30.0, 40.0), Range(50.0, 55.0)]
        self.assertEqual((labels.format, labels.kept, labels.zooms), ("longo", kept, []))
        self.assertEqual(labels.sequences, ["Compilacao", "Longo"])

    def test_speed_changes_are_ignored_and_preedited_sources_are_flagged(self):
        pre = r"E:\Bruto\2026-05-13_16-39-32_preedit.mp4"
        clips = [clip(1, 0.0, 2.0, 5.0, source=pre), clip(1, 2.0, 4.0, 9.0, source=pre, speed=2.0), clip(1, 4.0, 5.0, 20.0, source=pre)]
        (labels,) = labels_from_sequences([SequenceEdit("S", False, clips)])

        self.assertEqual(labels.kept, [Range(5.0, 7.0), Range(20.0, 21.0)])
        self.assertTrue(labels.preedited)

    def test_short_zoom_clip_one_frame_off_still_counts(self):
        # Clipe de zoom de 0,4 s em que o Premiere guardou 1 quadro (1/30 s) a mais na gravacao.
        one_frame_off = ClipEdit(1, 3.5, 3.9, BRUTO, 93.93, 94.363, 170.0)
        (labels,) = labels_from_sequences([SequenceEdit("S", True, [clip(1, 0.0, 3.5, 71.91), one_frame_off, clip(1, 3.9, 5.0, 96.4)])])

        self.assertEqual(labels.zooms, [Zoom(93.93, 94.36, 1.7)])

    def test_broll_outside_the_main_track_is_ignored(self):
        broll = r"E:\Downloads\[GREEN SCREEN HD] - meme.mp4"
        main = [clip(1, 0.0, 3.0, 10.0), clip(1, 3.0, 6.0, 20.0)]
        extra = [clip(3, 1.0, 2.0, 0.0, source=broll), clip(3, 4.0, 5.0, 7.0, source=broll)]

        labels, ignored = collect_labels([SequenceEdit("S", False, main + extra)])

        self.assertEqual([item.recording for item in labels], [BRUTO])
        self.assertEqual(ignored, [{"recording": broll, "reason": "fora da trilha principal (b-roll)"}])

    def test_whole_recording_without_cuts_is_not_a_lesson(self):
        whole = [clip(1, 0.0, 400.0, 0.0)]
        edited = [clip(1, 0.0, 10.0, 0.0), clip(1, 10.0, 20.0, 30.0)]
        other = r"E:\Bruto\outra.mp4"

        labels, ignored = collect_labels(
            [SequenceEdit("Inteira", False, whole), SequenceEdit("Editada", False, edited), SequenceEdit("Sozinha", False, [clip(1, 0.0, 300.0, 0.0, source=other)])]
        )

        (only,) = labels
        self.assertEqual((only.kept, only.sequences), ([Range(0.0, 10.0), Range(30.0, 40.0)], ["Editada"]))
        self.assertEqual(ignored, [{"recording": other, "reason": "sem cortes (gravacao inteira na sequencia)"}])

    def test_nothing_usable(self):
        self.assertEqual(labels_from_sequences([SequenceEdit("S", False, [clip(1, 0.0, 2.0, 5.0, speed=1.5)])]), [])

    def test_merge_ranges(self):
        merged = merge_ranges([Range(5.0, 6.0), Range(0.0, 2.0), Range(2.03, 3.0)])
        self.assertEqual(merged, [Range(0.0, 3.0), Range(5.0, 6.0)])


class FinalLabelsTest(unittest.TestCase):
    def test_zooms_of_the_exported_range_in_video_time_and_only_on_the_recording(self):
        meme = r"E:\Memes\meme.mp4"
        v1 = [
            clip(1, 0.0, 30.0, 100.0),
            clip(1, 30.0, 31.5, 300.0, scale=150.0),
            clip(1, 31.5, 50.0, 301.5),
            clip(1, 50.0, 51.0, 0.0, scale=200.0, source=meme),  # meme curto na trilha principal: fora
            clip(1, 51.0, 80.0, 400.0),
            clip(1, 80.0, 81.0, 500.0, scale=170.0),  # depois do trecho exportado
        ]
        sequence = SequenceEdit("Sequência 03", False, v1, 100.0)

        labels = final_labels(sequence, FINAL, 10.0, 55.0)

        self.assertEqual((labels.recording, labels.format, labels.final), (FINAL, "longo", True))
        self.assertEqual(labels.kept, [Range(0.0, 45.0)])
        self.assertEqual(labels.zooms, [Zoom(20.0, 21.5, 1.5)])
        self.assertEqual(labels.sequences, ["Sequência 03"])
        self.assertEqual(labels.sources, [BRUTO])  # pra nao ensinar de novo o que ja veio do bruto

    def test_zoom_heavy_range_keeps_the_normal_scale_by_time(self):
        # Short de 22 s cortado de uma sequencia longa: 6 zooms de 130%, cada um partido em 2 clipes.
        # Por contagem a escala "normal" seria 130 (12 clipes x 6); pelo tempo e 100 (15 s x 7,2 s).
        clips = [clip(1, 0.0, 40.0, 0.0)]
        t = 40.0
        for _ in range(6):
            clips += [clip(1, t, t + 2.5, t), clip(1, t + 2.5, t + 3.1, t + 2.5, scale=130.0), clip(1, t + 3.1, t + 3.7, t + 3.1, scale=130.0)]
            t += 3.7
        clips.append(clip(1, t, 100.0, t))

        labels = final_labels(SequenceEdit("Short cheio de zoom", True, clips, 100.0), FINAL, 40.0, t)

        self.assertEqual(len(labels.zooms), 12)
        self.assertEqual({zoom.level for zoom in labels.zooms}, {1.3})
        self.assertEqual(labels.zooms[0].start, 2.5)

    def test_without_range_the_whole_sequence_and_without_zoom_nothing(self):
        whole = SequenceEdit("Inteira", True, [clip(1, 0.0, 10.0, 0.0), clip(1, 10.0, 11.0, 20.0, scale=130.0)], 12.0)
        self.assertEqual(final_labels(whole, FINAL).kept, [Range(0.0, 12.0)])
        self.assertEqual(final_labels(whole, FINAL).format, "short")

        flat = SequenceEdit("Sem zoom", False, [clip(1, 0.0, 30.0, 0.0), clip(1, 30.0, 60.0, 90.0)], 60.0)
        self.assertIsNone(final_labels(flat, FINAL))
        self.assertIsNone(final_labels(SequenceEdit("Vazia", False, [], 10.0), FINAL))


if __name__ == "__main__":
    unittest.main()
