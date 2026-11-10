# Polar training analysis

A local Streamlit dashboard for Polar Flow exercise and RR CSV exports. It displays exercise timelines, heart-rate zones, Edwards training load, RR screening flags and descriptive five-minute RMSSD windows. Original files are not written to disk by the application. Treat uploaded health data as private; do not commit exports or expose the app publicly without authentication.

## Run

Tested with Python 3.12 (recommended). From the repository directory:

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1
```

Upload an `_RR.CSV` alone for RR analysis, a regular exercise CSV alone for exercise analysis, or both matching files. Exercise metadata, session duration comparisons and Edwards load are available only when an exercise CSV is supplied. The exercise export has summary headers and a separate sample header; RR exports have `duration` (milliseconds) and `offline` columns. Comma, semicolon and tab separators are supported. Files are parsed locally by the running Python app, with no AccessLink requests.

## Interpretation

Edwards load is the sum of minutes in 50–60%, 60–70%, 70–80%, 80–90% and 90–100% HRmax multiplied by 1–5 respectively. Zone lower bounds are inclusive; 100% is included in the final zone. Missing time and readings above HRmax are excluded, with coverage reported. This is not Polar's proprietary load calculation. Update HRmax in the sidebar to suit your measurements.

RR flags are broad plausibility and adjacent-change heuristics, not a clinical artifact detector. Flagged beats remain in the timeline; RMSSD never bridges flagged beats. Short or low-quality windows withhold RMSSD. Passing screening does not establish stable effort or signal validity. Exercise HRV must not be interpreted as resting or overnight recovery HRV.

RR timing assumes a common start and uses cumulative intervals. Matching durations cannot prove precise synchronization or that files belong to the same session. Timestamps are displayed as exported; no timezone is inferred.

## Validate

```sh
.venv/bin/python -m unittest discover -s tests -v
```

This first version supports one exercise at a time. Daily activity, multi-session trends, sleep analysis, persistent storage and Polar AccessLink OAuth ingestion are not implemented yet. No credentials are needed for CSV analysis.

## Optional RR artifact correction

After uploading an RR file (with or without an exercise file), enable **Apply RR artifact correction**. The app uses NeuroKit2 0.2.12 `signal_fixpeaks(method="Kubios", iterative=False)` for one auditable pass of the published Lipponen–Tarvainen algorithm. This is an independent open-source implementation, not a connection to commercial Kubios software or a guarantee of identical results.

The input is a zero-time boundary followed by cumulative RR durations in milliseconds, interpreted as inferred peak positions at a nominal 1,000 Hz time resolution. There is no ECG waveform or verified beat detection. The algorithm classifies ectopic, missed, extra and long/short events and can reposition, insert or delete inferred peaks. Original intervals remain unchanged. Corrected intervals retain their reconstructed elapsed times; recording boundaries must remain unchanged or the correction is rejected. Short recordings (under 30 intervals) and offline-flagged recordings are rejected rather than silently interpolated.

Downloads include raw intervals, corrected intervals, five-minute metric comparisons, and an audit of detected events referencing zero-based original peak indices (index zero is the inferred start boundary). Output intervals are marked corrected when their endpoint pair is absent from the original series; this accounts for inserted/deleted beats without pretending rows align one-to-one. The percentage is an output-interval burden, not a percentage of diagnosed abnormal heartbeats. Corrected RMSSD excludes residual heuristic flags and is withheld for windows with more than 5% corrected output intervals, as well as the existing quality/coverage checks.

Review correction visually: genuine exercise transitions may be classified as artifacts. Corrected exercise HRV remains descriptive and is not an overnight recovery measurement.

References: [NeuroKit signal_fixpeaks documentation](https://neuropsychology.github.io/NeuroKit/functions/signal.html#signal-fixpeaks); Lipponen & Tarvainen (2019), *A robust algorithm for heart rate variability time series artefact correction using novel beat classification*, [DOI](https://doi.org/10.1080/03091902.2019.1640306).

On Windows using the Python 3.12 environment from troubleshooting, update and launch with:

```powershell
git pull
.\.venv312\Scripts\python.exe -m pip install -r requirements.txt
.\.venv312\Scripts\python.exe -m streamlit run app.py
```

## Short-term DFA α1

The RR view calculates DFA α1 for **200 consecutive RR intervals with a 100-interval step**: intervals 1–200, 101–300, 201–400, etc. Only complete windows are used. Each result includes start/end interval numbers (one-based, inclusive), elapsed start/end seconds, midpoint time, mean HR, quality percentages, α1, log–log fit R² and status. A recording with N intervals produces `max(0, (N - 200) // 100 + 1)` windows.

The estimator is NeuroKit2 `fractal_dfa`, with **all integer scales 4–16 inclusive**, a demeaned cumulative profile, first-order (linear) detrending, and 50% overlapping internal segments (`overlap=True`). The slope of log fluctuation versus log scale is α1. Internal DFA segmentation is separate from the 100-interval step of the outer windows. No resampling to uniform time is performed.

Raw and corrected series have separate charts, tables and CSV downloads. Windows are indexed independently when correction adds/removes intervals; compare by elapsed time, not row number. Any residual heuristic flags, more than 5% corrected intervals, constant data or an undefined fit withhold the estimate. Flagged intervals are not deleted or concatenated across gaps. Fit R² describes linear scaling fit only; it is not a validated quality score. Genuine exercise transitions and correction can affect α1. This app does not derive aerobic/anaerobic thresholds or recovery scores from it.

The DFA view also includes a scatter plot with **mean heart rate (bpm) on the x-axis** and **DFA α1 on the y-axis**, for both raw and optionally corrected series. Each point uses the same 200 RR intervals for its HR and DFA estimate; HR is `60000 / mean(RR_ms)`. Withheld estimates are excluded. Overlapping points are not independent and are not connected in HR order or used to fit physiological thresholds. If no estimate passes screening, an explanatory message replaces the scatter plot.
