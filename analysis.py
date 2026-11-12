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


def time_windows(beats):
    """Shared complete 120 s windows, every 60 s, anchored at recording start.

    Assign intervals by end timestamp in (start, end]. Boundary intervals are
    not split. Nominal time bounds remain identical for raw/corrected streams.
    """
    from bisect import bisect_right
    if not beats:
        return
    times = [b['elapsed_s'] for b in beats]
    origin = times[0] - beats[0]['rr_ms'] / 1000
    count = max(0, int(math.floor((times[-1] - origin - 120 + 1e-7) / 60)) + 1)
    for index in range(count):
        start = origin + index * 60
        end = start + 120
        left = bisect_right(times, start + 1e-7)
        right = bisect_right(times, end + 1e-7)
        group = beats[left:right]
        if not group:
            continue
        n = len(group)
        yield group, dict(start_interval=left + 1, end_interval=right,
                          start_s=start, end_s=end, start_min=start / 60,
                          midpoint_min=(start + end) / 120, duration_s=120.,
                          interval_count=n,
                          flagged_pct=100 * sum(b['flagged'] for b in group) / n,
                          corrected_pct=100 * sum(b.get('corrected', False) for b in group) / n)


def rr_windows(beats):
    """Summary view of the same two-minute HRV windows used for spectra."""
    return hrv_windows(beats)


def dfa_windows(beats):
    """DFA alpha1, scales 4–16, in complete 120-second windows stepped by 60.

    Never remove intervals to manufacture a contiguous window. Raw or residual
    flags withhold the estimate; corrected output burden must be <= 5%.
    """
    import numpy as np
    import neurokit2 as nk

    rows = []
    for group, bounds in time_windows(beats):
        values = np.asarray([b['rr_ms'] for b in group], dtype=float)
        flagged = any(b['flagged'] for b in group)
        row = {**bounds, 'mean_hr_bpm': 60000 / float(np.mean(values)),
               'alpha1': None, 'fit_r2': None, 'status': 'ok'}
        if flagged:
            row['status'] = 'withheld: flagged intervals'
        elif row['corrected_pct'] > 5:
            row['status'] = 'withheld: more than 5% corrected'
        elif not np.isfinite(values).all() or np.any(values <= 0):
            row['status'] = 'withheld: invalid intervals'
        elif len(values) < 64:
            row['status'] = 'withheld: fewer than 64 intervals for DFA scales 4–16'
        elif np.ptp(values) < 1e-9:
            row['status'] = 'withheld: constant RR'
        else:
            alpha, info = nk.fractal_dfa(values, scale=list(range(4, 17)),
                                         overlap=True, integrate=True, order=1,
                                         multifractal=False, show=False)
            fluctuations = np.asarray(info['Fluctuations']).reshape(-1)
            if np.isfinite(alpha) and np.isfinite(fluctuations).all() and np.all(fluctuations > 0):
                row['alpha1'] = float(alpha)
                log_scale, log_f = np.log(info['scale']), np.log(fluctuations)
                residual = log_f - np.polyval(np.polyfit(log_scale, log_f, 1), log_scale)
                total = float(np.sum((log_f - log_f.mean()) ** 2))
                row['fit_r2'] = 1 - float(np.sum(residual ** 2)) / total if total > 0 else None
            else:
                row['status'] = 'withheld: undefined scaling fit'
        rows.append(row)
    return rows


def hrv_windows(beats):
    """120-second, 60-second-step HRV. PSD units ms²/Hz; band integrals ms².

    Spectral estimates use linear interpolation at 4 Hz, linear detrending and
    a full-window Hann periodogram. No gaps or flagged beats are interpolated.
    Respiration is only an unvalidated RSA spectral-peak candidate.
    """
    import numpy as np
    from scipy.signal import detrend, periodogram, find_peaks

    rows = []
    for group, bounds in time_windows(beats):
        rr = np.array([b['rr_ms'] for b in group], dtype=float)
        times = np.array([b['elapsed_s'] for b in group], dtype=float)
        row = dict(**bounds, mean_hr_bpm=60000 / float(np.mean(rr)),
                   rmssd_ms=None, lf_ms2=None, hf_ms2=None,
                   resampling_hz=4.0,
                   spectral_ceiling_hz=None, respiration_candidate_bpm=None,
                   respiration_peak_fraction=None, status='ok',
                   respiration_status='unavailable')
        rows.append(row)
        if row['flagged_pct'] or row['corrected_pct'] > 5:
            row['status'] = 'withheld: flagged intervals or more than 5% corrected'
            continue
        if (len(rr) < 2 or not np.isfinite(rr).all() or np.any(rr <= 0) or
                not np.isfinite(times).all() or np.any(np.diff(times) <= 0) or
                not np.allclose(np.diff(times), rr[1:] / 1000, atol=1e-5)):
            row['status'] = 'withheld: invalid or discontinuous timing'
            continue
        row['rmssd_ms'] = float(np.sqrt(np.mean(np.diff(rr) ** 2)))
        # Interpolation does not create independent high-frequency information.
        ceiling = min(1., 500 / float(np.mean(rr)))
        row['spectral_ceiling_hz'] = ceiling
        resampling_hz = row['resampling_hz']
        grid = np.arange(times[0], times[-1], 1 / resampling_hz)
        signal = detrend(np.interp(grid, times, rr), type='linear')
        freq, psd = periodogram(signal, fs=resampling_hz, window='hann', detrend=False,
                                scaling='density')

        def power(low, high):
            inside = (freq > low) & (freq < high)
            f = np.r_[low, freq[inside], high]
            p = np.interp(f, freq, psd)
            return float(np.trapezoid(p, f))

        duration = times[-1] - times[0]
        if duration >= 75:  # at least three cycles at the LF lower bound
            row['lf_ms2'] = power(.04, .15)
        else:
            row['status'] = 'LF withheld: less than 75 seconds of spectral coverage'
        if ceiling >= 1.:
            row['hf_ms2'] = power(.15, 1.)
        else:
            row['status'] += '; full HF withheld: mean beat rate cannot support 1 Hz'
        band = (freq >= .15) & (freq <= ceiling)
        candidates, _ = find_peaks(psd)
        candidates = [i for i in candidates if band[i] and
                      freq[i] > .15 + 1/duration and freq[i] < ceiling - 1/duration]
        if np.ptp(rr) < 1e-6 or not candidates:
            row['respiration_status'] = 'withheld: no interior spectral peak'
            continue
        peak = max(candidates, key=lambda i: psd[i])
        total = power(.15, ceiling) if ceiling > .15 else 0
        fraction = power(max(.15, freq[peak] - .03), min(ceiling, freq[peak] + .03)) / total if total > 1e-12 else 0
        row['respiration_peak_fraction'] = fraction
        if duration < 30 or fraction < .5:
            row['respiration_status'] = 'withheld: short window or weak spectral concentration'
        else:
            row['respiration_candidate_bpm'] = float(freq[peak] * 60)
            row['respiration_status'] = 'unvalidated RSA peak candidate; aliasing and exercise confounding possible'
    return rows


def correct_rr(beats):
    """One pass of NeuroKit's Lipponen–Tarvainen method on inferred beat times.

    Original peak indices are retained in the audit; split/deleted intervals mean
    corrected rows cannot be paired one-to-one with original rows.
    """
    import numpy as np
    import neurokit2 as nk

    if len(beats) < 30:
        raise ValueError('Correction requires at least 30 RR intervals.')
    if any('offline flag' in b['reason'] for b in beats):
        raise ValueError('Correction is unavailable for offline-flagged data; continuity is uncertain.')
    original = np.concatenate(([0.0], np.cumsum([b['rr_ms'] for b in beats])))
    info, peaks = nk.signal_fixpeaks(original, sampling_rate=1000,
                                     method='Kubios', iterative=False, show=False)
    peaks = np.asarray(peaks, dtype=float)
    if (len(peaks) < 2 or not np.isfinite(peaks).all() or
            np.any(np.diff(peaks) <= 0) or peaks[0] != original[0] or
            peaks[-1] != original[-1]):
        raise ValueError('Correction changed recording boundaries or produced invalid intervals; raw data retained.')
    intervals = np.diff(peaks)
    corrected = parse_rr('duration,offline\n' + '\n'.join(f'{v:.12g},false' for v in intervals))
    original_intervals = {(float(a), float(b)) for a, b in zip(original, original[1:])}
    for row, start, end in zip(corrected, peaks, peaks[1:]):
        row['elapsed_s'] = float(end / 1000)
        row['corrected'] = (float(start), float(end)) not in original_intervals
    audit = []
    for kind in ('ectopic', 'missed', 'extra', 'longshort'):
        for index in info.get(kind, []):
            index = int(index)
            audit.append({'category': kind, 'original_peak_index': index,
                          'elapsed_s': float(original[index] / 1000)})
    return corrected, audit


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
