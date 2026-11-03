# Polar training analysis

A local Streamlit dashboard for Polar Flow exercise and RR CSV exports. It displays exercise timelines, heart-rate zones, Edwards training load, RR screening flags and descriptive five-minute RMSSD windows. Original files are not written to disk by the application. Treat uploaded health data as private; do not commit exports or expose the app publicly without authentication.

## Run

Requires Python 3.12 or later. From the repository directory:

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1
```

Upload the regular exercise CSV, then the matching `_RR.CSV`. The exercise export has summary headers and a separate sample header; RR exports have `duration` (milliseconds) and `offline` columns. Comma, semicolon and tab separators are supported. Files are parsed locally by the running Python app, with no AccessLink requests.

## Interpretation

Edwards load is the sum of minutes in 50–60%, 60–70%, 70–80%, 80–90% and 90–100% HRmax multiplied by 1–5 respectively. Zone lower bounds are inclusive; 100% is included in the final zone. Missing time and readings above HRmax are excluded, with coverage reported. This is not Polar's proprietary load calculation. Update HRmax in the sidebar to suit your measurements.

RR flags are broad plausibility and adjacent-change heuristics, not a clinical artifact detector. Flagged beats remain in the timeline; RMSSD never bridges flagged beats. Short or low-quality windows withhold RMSSD. Passing screening does not establish stable effort or signal validity. Exercise HRV must not be interpreted as resting or overnight recovery HRV.

RR timing assumes a common start and uses cumulative intervals. Matching durations cannot prove precise synchronization or that files belong to the same session. Timestamps are displayed as exported; no timezone is inferred.

## Validate

```sh
.venv/bin/python -m unittest discover -s tests -v
```

This first version supports one exercise at a time. Daily activity, multi-session trends, sleep analysis, persistent storage and Polar AccessLink OAuth ingestion are not implemented yet. No credentials are needed for CSV analysis.
