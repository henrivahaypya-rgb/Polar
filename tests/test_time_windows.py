import unittest
from analysis import parse_rr, time_windows, dfa_windows, hrv_windows, rr_windows


def recording(rr, count):
    return parse_rr('duration,offline\n' + f'{rr},false\n' * count)


class TimeWindowTests(unittest.TestCase):
    def test_exact_bounds_and_incomplete_tail(self):
        beats = recording(500, 599)  # 299.5 s: omit 180–300 s
        windows = list(time_windows(beats))
        self.assertEqual([(r['start_s'], r['end_s']) for _, r in windows],
                         [(0, 120), (60, 180), (120, 240)])
        self.assertEqual(windows[0][1]['interval_count'], 240)
        self.assertEqual(windows[1][1]['start_interval'], 121)
        self.assertEqual(len(list(time_windows(recording(500, 600)))), 4)
        self.assertEqual(list(time_windows(recording(500, 239))), [])

    def test_all_metrics_share_bounds_at_different_heart_rates(self):
        for rr, count in [(400, 700), (800, 350)]:
            beats = recording(rr, count)
            tables = [dfa_windows(beats), hrv_windows(beats), rr_windows(beats)]
            expected = [(0, 120, 1), (60, 180, 2), (120, 240, 3)]
            for rows in tables:
                self.assertEqual([(r['start_s'], r['end_s'], r['midpoint_min']) for r in rows], expected)

    def test_correction_changes_counts_not_time_bounds(self):
        raw = recording(800, 300)
        corrected = recording(400, 600)
        a, b = list(time_windows(raw)), list(time_windows(corrected))
        self.assertEqual([(r['start_s'], r['end_s']) for _, r in a],
                         [(r['start_s'], r['end_s']) for _, r in b])
        self.assertEqual(a[0][1]['interval_count'] * 2, b[0][1]['interval_count'])

    def test_dfa_withholds_for_too_few_beats(self):
        row = dfa_windows(recording(2000, 60))[0]
        self.assertIsNone(row['alpha1'])
        self.assertIn('fewer than 64', row['status'])
