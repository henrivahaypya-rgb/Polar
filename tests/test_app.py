"""Exercise upload paths using Streamlit's script runner and synthetic CSVs."""
import io
import math
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest


def rr_file(count=450, constant=False):
    values = [800 if constant else 800 + 10 * math.sin(i * .3) for i in range(count)]
    return io.BytesIO(('duration,offline\n' + '\n'.join(f'{v},false' for v in values)).encode())


def exercise_file():
    return io.BytesIO(b'Sport,Duration\nRUNNING,00:06:00\nTime,HR (bpm)\n00:00:00,100\n00:00:01,110\n')


class DashboardTests(unittest.TestCase):
    def run_uploads(self, exercise, rr):
        with patch('streamlit.file_uploader', side_effect=[exercise, rr]):
            app = AppTest.from_file('app.py').run(timeout=60)
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        return app

    def test_rr_only_and_scatter_axes(self):
        app = self.run_uploads(None, rr_file())
        self.assertNotIn('Edwards load (AU)', [m.label for m in app.metric])
        self.assertIn('RR recording duration (min)', [m.label for m in app.metric])
        charts = app.get('arrow_vega_lite_chart')
        import json
        specs = [json.loads(c.proto.spec) for c in charts]
        scatter = next(s for s in specs if s.get('mark', {}).get('type') == 'circle')
        self.assertEqual(scatter['encoding']['x']['field'], 'Mean heart rate (bpm)')
        self.assertEqual(scatter['encoding']['y']['field'], 'DFA α1')

    def test_exercise_only(self):
        app = self.run_uploads(exercise_file(), None)
        self.assertIn('Edwards load (AU)', [m.label for m in app.metric])

    def test_combined(self):
        app = self.run_uploads(exercise_file(), rr_file())
        self.assertIn('Session duration minus RR duration', [m.label for m in app.metric])

    def test_no_valid_dfa_points(self):
        app = self.run_uploads(None, rr_file(constant=True))
        self.assertTrue(any('No windows passed' in m.value for m in app.info))

    def test_short_rr(self):
        app = self.run_uploads(None, rr_file(30))
        self.assertTrue(any('at least 200' in m.value for m in app.info))

    def test_invalid_rr(self):
        with patch('streamlit.file_uploader', side_effect=[None, io.BytesIO(b'bad,data\n')]):
            app = AppTest.from_file('app.py').run(timeout=30)
        self.assertFalse(app.exception)
        self.assertTrue(app.error)
