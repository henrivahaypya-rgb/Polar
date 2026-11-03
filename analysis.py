"""Polar Flow CSV parsing and transparent exercise metrics (no network access)."""
import csv
import io
import math
import statistics


def read_rows(data):
    text = data.decode('utf-8-sig') if isinstance(data, bytes) else data.lstrip('\ufeff')
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    return list(csv.reader(io.StringIO(text), dialect))


def seconds(value):
    parts = value.split(':')
    if len(parts) != 3:
        raise ValueError(f'Expected HH:MM:SS, received {value!r}')
    h, m, s = map(float, parts)
    if h < 0 or not 0 <= m < 60 or not 0 <= s < 60:
        raise ValueError('Invalid elapsed time')
    return h * 3600 + m * 60 + s


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def parse_exercise(data):
    rows = read_rows(data)
    if len(rows) < 4 or 'Sport' not in rows[0] or 'Duration' not in rows[0]:
        raise ValueError('Expected a Polar Flow exercise CSV with summary and sample headers.')
    summary = dict(zip(rows[0], rows[1]))
    header_index = next((i for i, row in enumerate(rows[2:], 2)
                         if 'Time' in row and 'HR (bpm)' in row), None)
    if header_index is None:
        raise ValueError('Exercise sample header is missing.')
    samples = []
    previous = -1
    for line, row in enumerate(rows[header_index + 1:], header_index + 2):
        if not any(row):
            continue
        if len(row) != len(rows[header_index]):
            raise ValueError(f'Exercise row {line} has an unexpected column count.')
        sample = dict(zip(rows[header_index], row))
        t = seconds(sample['Time'])
        if t <= previous:
            raise ValueError('Exercise times must be strictly increasing.')
        previous = t
        samples.append({'elapsed_s': t, **{k: number(v) for k, v in sample.items()
                                          if k not in ('Time', 'Sample rate')}})
    if not samples:
        raise ValueError('No exercise samples found.')
    return {'summary': summary, 'duration_s': seconds(summary['Duration']), 'samples': samples}


def parse_rr(data):
    rows = read_rows(data)
    if not rows or not {'duration', 'offline'}.issubset(rows[0]):
        raise ValueError('Expected an RR CSV with duration and offline columns.')
    beats, elapsed = [], 0.0
    previous = None
    for line, row in enumerate(rows[1:], 2):
        if not any(row):
            continue
        if len(row) != len(rows[0]):
            raise ValueError(f'RR row {line} has an unexpected column count.')
        entry = dict(zip(rows[0], row))
        rr = number(entry['duration'])
        if rr is None or rr <= 0:
            raise ValueError(f'RR row {line} must contain a positive finite interval.')
        flag = entry['offline'].strip().lower()
        if flag not in ('true', 'false'):
            raise ValueError(f'RR row {line} has an unknown offline flag.')
        reasons = []
        if not 250 <= rr <= 2000:
            reasons.append('outside 250–2000 ms')
        if previous is not None and abs(rr - previous) / previous > .20:
            reasons.append('change over 20%')
        if flag == 'true':
            reasons.append('offline flag')
        elapsed += rr / 1000
        beats.append({'elapsed_s': elapsed, 'rr_ms': rr, 'flagged': bool(reasons),
                      'reason': '; '.join(reasons)})
        previous = rr
    if not beats:
        raise ValueError('No RR intervals found.')
    return beats


def rr_windows(beats, window_s=300):
    """Descriptive exercise HRV; never join pairs across flagged beats or windows."""
    groups = {}
    for beat in beats:
        groups.setdefault(int(beat['elapsed_s'] // window_s), []).append(beat)
    result = []
    for index, group in sorted(groups.items()):
        clean = [b['rr_ms'] for b in group if not b['flagged']]
        diffs = [b['rr_ms'] - a['rr_ms'] for a, b in zip(group, group[1:])
                 if not a['flagged'] and not b['flagged']]
        span = group[-1]['elapsed_s'] - group[0]['elapsed_s']
        coverage = span / window_s
        flagged = sum(b['flagged'] for b in group) / len(group)
        eligible = coverage >= .9 and flagged <= .05 and len(diffs) >= 30
        result.append({'start_min': index * window_s / 60,
                       'coverage_pct': coverage * 100, 'flagged_pct': flagged * 100,
                       'mean_hr_bpm': 60000 / statistics.mean(clean) if clean else None,
                       'rmssd_ms': math.sqrt(statistics.mean(d*d for d in diffs)) if eligible else None,
                       'status': 'descriptive only' if eligible else 'insufficient coverage or quality'})
    return result


def training_metrics(exercise, resting_hr=44, maximum_hr=168):
    """Edwards load: minutes in 50–60/60–70/70–80/80–90/90–100% HRmax × 1–5."""
    if not 0 < resting_hr < maximum_hr:
        raise ValueError('Resting HR must be positive and below maximum HR.')
    zones = [0.0] * 5
    below = above = missing = 0.0
    samples = exercise['samples']
    for i, sample in enumerate(samples):
        end = samples[i+1]['elapsed_s'] if i+1 < len(samples) else min(
            sample['elapsed_s'] + 1, exercise['duration_s'])
        # Do not assume missing seconds have the previous heart rate.
        dt = max(0, min(1, end - sample['elapsed_s'], exercise['duration_s'] - sample['elapsed_s']))
        hr = sample['HR (bpm)']
        if hr is None or hr <= 0:
            missing += dt
        elif hr > maximum_hr:
            above += dt
        elif hr < .5 * maximum_hr:
            below += dt
        else:
            zone = min(4, int(round(hr / maximum_hr * 100, 8) // 10) - 5)
            zones[zone] += dt
    observed = sum(zones) + below + above
    return {'zone_minutes': [v / 60 for v in zones],
            'edwards_load': sum((i+1) * v / 60 for i, v in enumerate(zones)),
            'coverage_pct': observed / exercise['duration_s'] * 100 if exercise['duration_s'] else 0,
            'below_zone_minutes': below / 60, 'above_max_minutes': above / 60,
            'missing_hr_seconds': missing}
