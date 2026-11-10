import unittest
from analysis import parse_exercise, parse_rr, rr_windows, training_metrics, correct_rr
import copy
import math


class AnalysisTests(unittest.TestCase):
    def test_correction_repairs_missed_beat_and_preserves_raw(self):
        values = [800 + 20 * math.sin(i * .3) for i in range(1000)]
        values[200] = 1600
        beats = parse_rr('duration,offline\n' + '\n'.join(f'{v},false' for v in values))
        original = copy.deepcopy(beats)
        corrected, audit = correct_rr(beats)
        self.assertEqual(beats, original)
        self.assertTrue(any(a['category'] == 'missed' for a in audit))
        self.assertEqual(len(corrected), len(beats) + 1)
        self.assertAlmostEqual(corrected[-1]['elapsed_s'], beats[-1]['elapsed_s'])
        self.assertLess(max(b['rr_ms'] for b in corrected), 900)
        self.assertTrue(any(b['corrected'] for b in corrected))
        self.assertTrue(all(corrected[i]['elapsed_s'] < corrected[i+1]['elapsed_s']
                            for i in range(len(corrected)-1)))

    def test_correction_preserves_clean_signal(self):
        values = [800 + 20 * math.sin(i * .3) for i in range(500)]
        beats = parse_rr('duration,offline\n' + '\n'.join(f'{v},false' for v in values))
        corrected, audit = correct_rr(beats)
        self.assertEqual(audit, [])
        self.assertFalse(any(b['corrected'] for b in corrected))
        for raw, output in zip(beats, corrected):
            self.assertAlmostEqual(raw['rr_ms'], output['rr_ms'], places=7)

    def test_correction_refuses_short_or_offline_data(self):
        for data in ['500,false\n' * 10, '500,true\n' * 40]:
            with self.assertRaises(ValueError):
                correct_rr(parse_rr('duration,offline\n' + data))

    def test_heavily_corrected_window_withholds_hrv(self):
        beats = [{'elapsed_s': i, 'rr_ms': 800, 'flagged': False, 'corrected': i < 40}
                 for i in range(1, 300)]
        self.assertIsNone(rr_windows(beats)[0]['rmssd_ms'])

    def test_rr_bom_and_timing(self):
        beats = parse_rr(b'\xef\xbb\xbfduration,offline\n500,false\n600,false\n900,true\n')
        self.assertEqual(beats[-1]['elapsed_s'], 2)
        self.assertFalse(beats[1]['flagged'])
        self.assertTrue(beats[2]['flagged'])

    def test_invalid_intervals(self):
        for value in ['0', '-2', 'nan', 'inf', 'oops']:
            with self.assertRaises(ValueError):
                parse_rr(f'duration,offline\n{value},false\n')

    def test_short_window_withholds_rmssd(self):
        self.assertIsNone(rr_windows(parse_rr('duration,offline\n500,false\n510,false\n'))[0]['rmssd_ms'])

    def test_rmssd_does_not_bridge_artifacts(self):
        beats = [{'elapsed_s': i, 'rr_ms': 500 if i % 2 else 510, 'flagged': False} for i in range(1, 300)]
        beats[100]['rr_ms'] = 2000
        beats[100]['flagged'] = True
        self.assertAlmostEqual(rr_windows(beats)[0]['rmssd_ms'], 10)

    def test_load_and_missing_seconds(self):
        data = 'Sport,Duration\nRUNNING,00:00:10\nTime,HR (bpm)\n00:00:00,100\n00:00:01,120\n00:00:09,200\n'
        exercise = parse_exercise(data)
        metrics = training_metrics(exercise, 50, 200)
        self.assertAlmostEqual(metrics['edwards_load'], 8/60)
        self.assertEqual(metrics['coverage_pct'], 30)

    def test_reject_wrong_file(self):
        with self.assertRaises(ValueError):
            parse_exercise('duration,offline\n500,false\n')


if __name__ == '__main__':
    unittest.main()
