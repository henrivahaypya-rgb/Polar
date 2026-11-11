import unittest
from unittest.mock import patch
import numpy as np
from analysis import hrv_200_windows


def beats(frequency=.3, baseline=400, amplitude=10, count=200):
    rows, t = [], 0.
    for _ in range(count):
        rr = baseline + amplitude * np.sin(2 * np.pi * frequency * t)
        t += rr / 1000
        rows.append(dict(elapsed_s=t, rr_ms=rr, flagged=False))
    return rows


class HRVTests(unittest.TestCase):
    def test_spectrum_uses_four_hz_resampling(self):
        from scipy.signal import periodogram
        group = beats()
        with patch('scipy.signal.periodogram', wraps=periodogram) as spectrum:
            hrv_200_windows(group)
        self.assertEqual(spectrum.call_args.kwargs['fs'], 4.0)
        expected = len(np.arange(group[0]['elapsed_s'], group[-1]['elapsed_s'], .25))
        self.assertEqual(len(spectrum.call_args.args[0]), expected)

    def test_hf_power_and_respiration(self):
        group = beats()
        row = hrv_200_windows(group)[0]
        self.assertEqual(row['resampling_hz'], 4.0)
        expected = np.sqrt(np.mean(np.diff([b['rr_ms'] for b in group]) ** 2))
        self.assertAlmostEqual(row['rmssd_ms'], expected)
        self.assertGreater(row['hf_ms2'], 35)
        self.assertLess(row['hf_ms2'], 60)  # input sinusoid variance = 50 ms²
        self.assertLess(row['lf_ms2'], 1)
        self.assertAlmostEqual(row['respiration_candidate_bpm'], 18, delta=1)

    def test_lf_sinusoid(self):
        row = hrv_200_windows(beats(frequency=.1))[0]
        self.assertGreater(row['lf_ms2'], 40)
        self.assertLess(row['hf_ms2'], 1)

    def test_sampling_limit(self):
        row = hrv_200_windows(beats(baseline=800))[0]
        self.assertIsNone(row['hf_ms2'])
        self.assertIsNotNone(row['lf_ms2'])

    def test_flags_and_correction_limit(self):
        group = beats()
        group[5]['flagged'] = True
        self.assertIsNone(hrv_200_windows(group)[0]['rmssd_ms'])
        group[5]['flagged'] = False
        for b in group[:11]:
            b['corrected'] = True
        self.assertIsNone(hrv_200_windows(group)[0]['hf_ms2'])

    def test_windows_constant_and_short(self):
        self.assertEqual(len(hrv_200_windows(beats(count=399))), 2)
        self.assertEqual(hrv_200_windows(beats(count=199)), [])
        row = hrv_200_windows(beats(amplitude=0))[0]
        self.assertEqual(row['rmssd_ms'], 0)
        self.assertIsNone(row['respiration_candidate_bpm'])
        self.assertIsNone(hrv_200_windows(beats(baseline=300))[0]['lf_ms2'])

    def test_gap_withholds(self):
        group = beats()
        group[40]['elapsed_s'] += .1
        self.assertIsNone(hrv_200_windows(group)[0]['rmssd_ms'])
