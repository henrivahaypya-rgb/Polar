import pandas as pd
import streamlit as st

from analysis import parse_exercise, parse_rr, rr_windows, training_metrics, number

st.set_page_config(page_title='Polar training analysis', layout='wide')
st.title('Polar training analysis')
st.write('Import a Polar Flow exercise CSV and optionally its matching RR CSV. Files are processed in this app without being saved to disk.')
exercise_file = st.file_uploader('Exercise CSV', type=['csv'], key='exercise')
rr_file = st.file_uploader('Matching RR CSV (optional)', type=['csv'], key='rr')
if exercise_file is None:
    st.info('Upload an exercise CSV to begin. Sleep and AccessLink integration are planned; this version analyzes exported exercises.')
    st.stop()
try:
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
        difference = exercise['duration_s'] - rr_duration
        st.subheader('RR quality and exercise HRV')
        a, b, c = st.columns(3)
        a.metric('RR intervals', f'{len(beats):,}')
        b.metric('Flagged intervals', f"{sum(b['flagged'] for b in beats):,}")
        c.metric('Session duration minus RR duration', f'{difference:.3f} s')
        st.caption('RR durations are interpreted as milliseconds. Beat times are reconstructed from their cumulative duration; alignment assumes the first interval begins at exercise start. RR exports have no absolute timestamps.')
        if abs(difference) > max(10, exercise['duration_s'] * .01):
            st.warning('Durations differ substantially. Confirm that the files belong to the same session. RR data is shown separately without claiming synchronization.')
        st.warning('Exercise HRV is not a resting recovery score. Motion, effort and breathing affect it. Screening flags are heuristics, not verified artifact correction; stable intensity is not automatically established.')
        st.caption('Flags: intervals outside 250–2,000 ms, changes over 20% from the preceding interval, or offline=true. RMSSD uses adjacent unflagged pairs within each five-minute window. Windows require ≥90% time coverage, ≤5% flagged intervals and ≥30 pairs.')
        frame = pd.DataFrame(beats)
        frame['Minutes'] = frame['elapsed_s'] / 60
        st.line_chart(frame.set_index('Minutes')[['rr_ms']])
        windows = pd.DataFrame(rr_windows(beats))
        st.dataframe(windows, hide_index=True)
        st.download_button('Download RR window metrics', windows.to_csv(index=False), 'rr_windows.csv', 'text/csv')
        with st.expander('Flagged intervals'):
            st.dataframe(frame[frame['flagged']], hide_index=True)
except (ValueError, KeyError, UnicodeError) as error:
    st.error(f'Cannot analyze these files: {error}')
