import pandas as pd
import streamlit as st

from analysis import parse_exercise, parse_rr, rr_windows, training_metrics, number, correct_rr, dfa_windows, hrv_windows


@st.cache_data(show_spinner='Calculating 120-second HRV…', max_entries=4)
def cached_hrv(beats):
    return hrv_windows(beats)


def show_hrv(beats, label):
    st.subheader(f'120-second HRV — {label}')
    rows = cached_hrv(beats)
    if not rows:
        st.info('At least 120 seconds of RR recording are required; incomplete final windows are omitted.')
        return
    results = pd.DataFrame(rows)
    st.caption('Same 120-second windows and 60-second step as DFA. RMSSD in ms; LF (0.04–0.15 Hz) and HF (0.15–1.0 Hz) in ms². Spectrum: 4 Hz linear interpolation, linear detrending, full-window Hann periodogram. Any flagged beat or more than 5% correction withholds all estimates. LF requires 75 seconds; short-window LF remains exploratory. Full HF is withheld below a mean heart rate of 120 bpm because interpolation cannot restore beat-sampling bandwidth.')
    st.line_chart(results.set_index('midpoint_min')[['rmssd_ms']])
    st.line_chart(results.set_index('midpoint_min')[['lf_ms2', 'hf_ms2']])
    st.warning('Respiration is an experimental estimate from the dominant RR oscillation (RSA), not a measured breathing rate. Motion, nonstationary effort, harmonics and aliasing can produce misleading peaks. Slow breathing below 9 breaths/min is outside the search band. Absence of an estimate does not mean absence of breathing.')
    st.caption('Search: 0.15 Hz to the lesser of 1 Hz and half the mean beat rate. Only interior peaks with ≥50% of search-band power within ±0.03 Hz and ≥30 seconds of coverage are reported. These are heuristic screening rules, not validated confidence limits.')
    st.line_chart(results.set_index('midpoint_min')[['respiration_candidate_bpm']])
    st.dataframe(results, hide_index=True)
    st.download_button(f'Download {label} 120-second HRV', results.to_csv(index=False), f'hrv_120s_{label}.csv', 'text/csv')


@st.cache_data(show_spinner='Correcting RR artifacts…', max_entries=4)
def cached_correction(beats):
    return correct_rr(beats)


@st.cache_data(show_spinner='Calculating DFA α1…', max_entries=4)
def cached_dfa(beats):
    return dfa_windows(beats)


def show_dfa(beats, label):
    st.subheader(f'DFA α1 — {label}')
    rows = cached_dfa(beats)
    if not rows:
        st.info('DFA requires at least 120 seconds of recording. Incomplete final windows are omitted.')
        return
    results = pd.DataFrame(rows)
    st.caption('Scales: every integer from 4 to 16 beats. Windows: 120 seconds, advanced by 60 seconds (50% overlap), plotted at their time midpoint. DFA uses a demeaned cumulative profile, linear detrending and 50% overlapping internal segments. Any remaining flagged intervals, or more than 5% corrected intervals, withhold α1; intervals are never removed to join gaps. At least 64 intervals are required for DFA scales 4–16. Fit R² describes the log–log scaling fit, not physiological validity.')
    st.line_chart(results.set_index('midpoint_min')[['alpha1']])
    st.markdown('**DFA α1 versus mean heart rate**')
    valid = results.dropna(subset=['alpha1', 'mean_hr_bpm'])
    if valid.empty:
        st.info('No windows passed the quality checks for the heart-rate plot.')
    else:
        plot = valid.rename(columns={'mean_hr_bpm': 'Mean heart rate (bpm)', 'alpha1': 'DFA α1'})
        st.scatter_chart(plot, x='Mean heart rate (bpm)', y='DFA α1')
    st.caption('Each point represents the same 120-second window used for DFA. Mean heart rate = 60,000 / mean RR in milliseconds. Overlapping windows are not independent; points are not connected or used to infer a threshold.')
    st.dataframe(results, hide_index=True)
    st.download_button(f'Download {label} DFA α1', results.to_csv(index=False), f'dfa_alpha1_120s_{label}.csv', 'text/csv')

st.set_page_config(page_title='Polar training analysis', layout='wide')
st.title('Polar training analysis')
st.write('Import a Polar Flow RR CSV on its own, an exercise CSV, or both matching files. Files are processed in this app without being saved to disk.')
exercise_file = st.file_uploader('Exercise CSV (optional)', type=['csv'], key='exercise')
rr_file = st.file_uploader('RR CSV (can be analyzed alone)', type=['csv'], key='rr')
if exercise_file is None and rr_file is None:
    st.info('Upload an RR CSV or an exercise CSV to begin. Sleep and AccessLink integration are planned.')
    st.stop()
try:
    exercise = None
    if exercise_file is not None:
        exercise = parse_exercise(exercise_file.getvalue())
        summary = exercise['summary']
        maximum_default = number(summary.get('HR max')) or 190
        maximum = st.sidebar.number_input('Maximum heart rate (bpm)', min_value=60, max_value=250, value=int(maximum_default))
        rest_default = min(int(number(summary.get('HR sit')) or 60), maximum - 1)
        resting = st.sidebar.number_input('Resting heart rate (bpm)', min_value=20, max_value=maximum-1, value=max(20, rest_default))
        st.sidebar.caption('HR sit is used as the initial resting value when present. Edwards load uses HRmax only.')
        metrics = training_metrics(exercise, resting, maximum)
        st.subheader(f"{summary.get('Sport', 'Exercise')} · {summary.get('Date', '')} · {summary.get('Start time', '')}")
        a, b, c, d = st.columns(4)
        a.metric('Duration', summary['Duration'])
        b.metric('Distance (km)', summary.get('Total distance (km)', '—'))
        c.metric('Average HR (bpm)', summary.get('Average heart rate (bpm)', '—'))
        d.metric('Edwards load (AU)', f"{metrics['edwards_load']:.1f}")
        st.caption(f"HR coverage: {metrics['coverage_pct']:.1f}%. Load = minutes in each HRmax zone × its weight (1–5). This is not Polar Cardio Load; it is not directly comparable between people.")
        zones = pd.DataFrame({'Zone': ['50–60%', '60–70%', '70–80%', '80–90%', '90–100%'], 'Minutes': metrics['zone_minutes']})
        st.bar_chart(zones.set_index('Zone'))
        if metrics['above_max_minutes']:
            st.warning(f"{metrics['above_max_minutes']:.2f} minutes above configured HRmax are excluded from load. Check HRmax and signal quality.")
        st.caption(f"Time below 50% HRmax: {metrics['below_zone_minutes']:.2f} minutes. Missing samples are not filled.")
        samples = pd.DataFrame(exercise['samples'])
        samples['Minutes'] = samples['elapsed_s'] / 60
        st.subheader('Exercise timeline')
        available = [c for c in ['HR (bpm)', 'Speed (km/h)', 'Power (W)', 'Cadence', 'Altitude (m)'] if c in samples and samples[c].notna().any()]
        selected = st.selectbox('Measurement', available)
        st.line_chart(samples.set_index('Minutes')[[selected]])
        st.download_button('Download normalized exercise samples', samples.to_csv(index=False), 'exercise_samples.csv', 'text/csv')
    if rr_file:
        beats = parse_rr(rr_file.getvalue())
        rr_duration = beats[-1]['elapsed_s']
        difference = exercise['duration_s'] - rr_duration if exercise else None
        st.subheader('RR quality and exercise HRV')
        a, b, c = st.columns(3)
        a.metric('RR intervals', f'{len(beats):,}')
        b.metric('Flagged intervals', f"{sum(b['flagged'] for b in beats):,}")
        if difference is not None:
            c.metric('Session duration minus RR duration', f'{difference:.3f} s')
        else:
            c.metric('RR recording duration (min)', f'{rr_duration / 60:.2f}')
            st.info('RR-only analysis: exercise metadata and training load require an exercise CSV.')
        st.caption('RR durations are interpreted as milliseconds. Beat times are reconstructed from their cumulative duration; alignment with an exercise, when supplied, assumes a common start. RR exports have no absolute timestamps.')
        if difference is not None and abs(difference) > max(10, exercise['duration_s'] * .01):
            st.warning('Durations differ substantially. Confirm that the files belong to the same session. RR data is shown separately without claiming synchronization.')
        st.warning('Exercise HRV is not a resting recovery score. Motion, effort and breathing affect it. Screening flags are heuristics, not verified artifact correction; stable intensity is not automatically established.')
        st.caption('Flags: intervals outside 250–2,000 ms, changes over 20% from the preceding interval, or offline=true. RMSSD uses adjacent unflagged pairs within each 120-second window, advanced by 60 seconds. Any flagged interval or more than 5% corrected intervals withholds estimates.')
        frame = pd.DataFrame(beats)
        frame['Minutes'] = frame['elapsed_s'] / 60
        st.line_chart(frame.set_index('Minutes')[['rr_ms']])
        windows = pd.DataFrame(rr_windows(beats))
        st.dataframe(windows, hide_index=True)
        st.download_button('Download RR window metrics', windows.to_csv(index=False), 'rr_windows_120s.csv', 'text/csv')
        with st.expander('Flagged intervals'):
            st.dataframe(frame[frame['flagged']], hide_index=True)
        st.caption('DFA α1 describes short-term RR correlations. Artifact correction, breathing and exercise transitions affect it; this app does not infer training thresholds from α1.')
        show_dfa(beats, 'raw')
        show_hrv(beats, 'raw')
        st.subheader('Automatic RR artifact correction')
        st.caption('One correction pass using NeuroKit2’s Kubios method. This is an independent implementation of the published algorithm, not commercial Kubios software. Raw intervals remain unchanged. The method can insert, remove or reposition inferred beats; exercise-related changes may be misclassified.')
        try:
            corrected, audit = cached_correction(beats)
            changed = sum(b['corrected'] for b in corrected)
            st.metric('Corrected output intervals', f'{changed} / {len(corrected)}')
            st.caption('An output interval is marked corrected if either endpoint differs from the original interval. The audit lists detections from the single pass, not confirmed physiological abnormalities.')
            raw_plot = frame[['Minutes', 'rr_ms']].rename(columns={'rr_ms': 'Raw RR (ms)'})
            corrected_frame = pd.DataFrame(corrected)
            corrected_frame['Minutes'] = corrected_frame['elapsed_s'] / 60
            corrected_plot = corrected_frame[['Minutes', 'rr_ms']].rename(columns={'rr_ms': 'Corrected RR (ms)'})
            st.line_chart(pd.merge(raw_plot, corrected_plot, on='Minutes', how='outer').sort_values('Minutes').set_index('Minutes'))
            comparison = pd.DataFrame(rr_windows(beats), columns=['start_min', 'rmssd_ms', 'status']).merge(
                pd.DataFrame(rr_windows(corrected), columns=['start_min', 'rmssd_ms', 'status']), on='start_min', suffixes=('_raw', '_corrected'))
            st.subheader('Raw versus corrected 120-second metrics')
            st.caption('Raw and corrected metrics are withheld for remaining flags and are withheld when more than 5% of output intervals in a window were corrected. Correction does not establish stable effort or make exercise HRV a recovery score.')
            st.dataframe(comparison, hide_index=True)
            st.download_button('Download corrected RR intervals', corrected_frame.to_csv(index=False), 'rr_corrected.csv', 'text/csv')
            st.download_button('Download raw RR intervals', frame.to_csv(index=False), 'rr_raw.csv', 'text/csv')
            st.download_button('Download raw/corrected window comparison', comparison.to_csv(index=False), 'rr_comparison_120s.csv', 'text/csv')
            audit_frame = pd.DataFrame(audit, columns=['category', 'original_peak_index', 'elapsed_s'])
            with st.expander('Correction audit'):
                st.dataframe(audit_frame, hide_index=True)
                st.download_button('Download correction audit', audit_frame.to_csv(index=False), 'rr_correction_audit.csv', 'text/csv')
            st.caption('Correction can change interval counts. Raw and corrected windows share the same 120-second time bounds; interval counts can differ after correction.')
            show_dfa(corrected, 'corrected')
            show_hrv(corrected, 'corrected')
        except (ValueError, IndexError, ZeroDivisionError) as error:
            st.warning(f'Correction unavailable: {error}')
except (ValueError, KeyError, UnicodeError) as error:
    st.error(f'Cannot analyze these files: {error}')
