import unittest
from analysis import parse_exercise, parse_rr, rr_windows, training_metrics, correct_rr, dfa_windows
import copy
import math


class AnalysisTests(unittest.TestCase):
    def test_dfa_window_counts_and_times(self):
        import numpy as np
        values = 800 + np.random.default_rng(7).normal(0, 10, 450)
        beats = parse_rr('duration,offline\n' + '\n'.join(f'{v},false' for v in values))
        windows = dfa_windows(beats)
        self.assertEqual([(w['start_interval'], w['end_interval']) for w in windows],
                         [(1, 200), (101, 300), (201, 400)])
        self.assertAlmostEqual(windows[0]['start_s'], 0)
        self.assertAlmostEqual(windows[1]['start_s'], sum(values[:100]) / 1000)
        self.assertAlmostEqual(windows[0]['end_s'], sum(values[:200]) / 1000)
        self.assertEqual(len(dfa_windows(beats[:200])), 1)
        self.assertEqual(dfa_windows(beats[:199]), [])
        self.assertTrue(all(w['alpha1'] is not None for w in windows))

    def test_dfa_distinguishes_noise_correlations(self):
        import numpy as np
        noise = np.random.default_rng(42).normal(0, 1, 3000)
        estimates = []
        for values in [800 + noise, 800 + np.cumsum(noise)]:
            beats = parse_rr('duration,offline\n' + '\n'.join(f'{v},false' for v in values))
            estimates.append(np.mean([w['alpha1'] for w in dfa_windows(beats)]))
        self.assertTrue(.4 < estimates[0] < .8)
        self.assertTrue(1.2 < estimates[1] < 1.8)

    def test_dfa_withholds_without_deleting_intervals(self):
        beats = parse_rr('duration,offline\n' + '\n'.join(f'{800 + 5*math.sin(i)},false' for i in range(200)))
        beats[20]['flagged'] = True
        self.assertIsNone(dfa_windows(beats)[0]['alpha1'])
        beats[20]['flagged'] = False
        for b in beats[:11]:
            b['corrected'] = True
        self.assertIsNone(dfa_windows(beats)[0]['alpha1'])
        beats[10]['corrected'] = False
        self.assertIsNotNone(dfa_windows(beats)[0]['alpha1'])
        constant = parse_rr('duration,offline\n' + '800,false\n' * 200)
        self.assertIsNone(dfa_windows(constant)[0]['alpha1'])

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
