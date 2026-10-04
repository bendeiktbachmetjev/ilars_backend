# Doctor API v2: new fields for the doctor portal

This page lists what the backend now sends to the doctor portal in addition to
what it sent before. It covers two endpoints: `GET /getPatients` (the patient
list) and `GET /getPatientDetail` (one patient's charts).

Code: [`src/routes/patients.py`](../src/routes/patients.py),
[`src/services/patient_views.py`](../src/services/patient_views.py) ·
Tests: [`tests/test_patient_views.py`](../tests/test_patient_views.py)

## In short

- **Only additions.** No key was removed, renamed or changed. The old portal
  keeps working against this backend.
- **No new endpoint and no database change.** No migration, table, column or index.
  All the new data was already in the database; the portal just did not get it.
- **Same access rules.** A doctor sees exactly the same patients as before. The
  new data belongs to those patients only.
- **One new optional parameter:** `GET /getPatients?include=lars_history`.
- **Responses are now compressed (gzip)** when they are larger than 1 KB.
  Browsers unpack them on their own. The patient list shrinks about 10 times.

## Rules for every new field

- `null` means "not recorded". A missing value is never sent as `0`.
- Dates are `"YYYY-MM-DD"` (UTC calendar day).
- Every list is sorted oldest to newest, one item per date.
- `as_of_date` is "today" according to the database (UTC). The portal should use
  it for every "days ago" and "day N" calculation, so the screen and the server
  always agree.

## `GET /getPatientDetail?patient_code=…`

Unchanged: `lars_scores`, `eq5d5l_scores`, `daily_entries` (last 730 days),
`daily_steps`, and every error response.

### New top-level keys

| Key | What it holds |
|---|---|
| `as_of_date` | Today's date on the server |
| `weekly_entries` | **Every** weekly LARS questionnaire, including ones saved without a total score |
| `eq5d5l_entries` | **Every** EQ-5D-5L questionnaire, including ones saved without the 0–100 "health today" score (VAS) |
| `monthly_entries` | Every monthly quality-of-life questionnaire. The portal got none of these before. |

The old `lars_scores` and `eq5d5l_scores` still skip rows without a total or a VAS.
The new arrays keep them.

### `weekly_entries[]`

| Key | Meaning |
|---|---|
| `date` | Day of the questionnaire |
| `score` | Total LARS score 0–42 as the app saved it. `null` if the app did not save one. |
| `points_total` | Total calculated by the backend from the five answers |
| `answers.<item>` | Which answer the patient picked (0 = first option) |
| `points.<item>` | LARS points for that answer |

The five items: `flatus_control`, `liquid_stool_leakage`, `bowel_frequency`,
`repeat_bowel_opening`, `urgency_to_toilet`. Points follow the standard LARS
table (Emmertsen & Laurberg 2012), the same table both patient apps use:

| Item | answer 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| `flatus_control` | 0 | 4 | 7 | — |
| `liquid_stool_leakage` | 0 | 3 | 3 | — |
| `bowel_frequency` | 4 | 2 | 0 | 5 |
| `repeat_bowel_opening` | 0 | 9 | 11 | — |
| `urgency_to_toilet` | 0 | 11 | 16 | — |

For `bowel_frequency`: 0 = more than 7 times a day, 1 = 4–7, 2 = 1–3, 3 = less than once a day.
To plot a score, use `score`, or `points_total` when `score` is `null`.

### `eq5d5l_entries[]`

| Key | Meaning |
|---|---|
| `date` | Day of the questionnaire |
| `vas` | "Health today" 0–100, or `null` |
| `levels.mobility`, `levels.self_care`, `levels.usual_activities`, `levels.pain_discomfort`, `levels.anxiety_depression` | EuroQol level **1–5** (1 = no problems, 5 = unable / extreme problems). The database stores 0–4; the backend adds 1. |

No EQ-5D index (utility) value is sent: there is no official value set for
Lithuania or Turkey.

### `monthly_entries[]`

| Key | Range | Direction |
|---|---|---|
| `date` | | |
| `qol_score` | 0–10, may be `null` | higher = better |
| `avoid_travel`, `avoid_social`, `embarrassed`, `worry_notice`, `depressed` | 1–4 | 1 = not at all, 4 = very much: **higher = worse** |
| `control`, `satisfaction` | 0–10 | higher = better |

### Six new keys on every `daily_entries[]` row

| Key | Values |
|---|---|
| `pads_used` | pads used that day (number) |
| `urgency` | `true` / `false` |
| `night_stools` | `true` / `false` |
| `leakage` | `"none"`, `"liquid"` or `"solid"` (compare the text; `"none"` is not empty) |
| `incomplete_evacuation` | `true` / `false` |
| `activity_interfere` | 0–10. Only the web app asks this; the mobile app always saves 0. |

## `GET /getPatients?status=…&include=…`

Unchanged: which patients are listed, their order, the existing keys, and the
early reply `{"status": "ok", "patients": []}` for a doctor without a hospital
(that reply has no `as_of_date`).

New: `as_of_date` at the top level, and on every patient:

| Key | What it holds |
|---|---|
| `first_lars_score`, `first_lars_date` | The first LARS score with a total (the starting point) |
| `lars_recent` | The last 12 LARS scores `[{date, score}]`, for the small trend line. The last item equals `last_lars_score`. |
| `lars_history` | **Only with `include=lars_history`.** All LARS scores `[{date, score}]`, for the cohort chart. |
| `first_eq5d5l_score`, `first_eq5d5l_date` | The first EQ-5D-5L VAS |
| `prev_eq5d5l_score`, `prev_eq5d5l_date` | The VAS before the latest one, for "VAS dropped by N since last time" |
| `eq5d5l_count` | Number of EQ-5D-5L questionnaires, with or without a VAS |
| `last_dates` | `{daily, weekly, monthly, eq5d5l}`: the newest date of each questionnaire type, with or without a score |
| `last_entry_date` | The newest of the four `last_dates`. It can be one day after `as_of_date`, because the web app saves the browser's local date. Show that as "today". |
| `adherence_30d` | `{days_with_entry, days_expected}`, see below |

`last_lars_*` and `last_eq5d5l_*` keep their old meaning (newest row **with** a
score). `include` ignores unknown values, so the portal can always send it.

### Adherence (`adherence_30d`)

"On how many days did the patient fill in something?" The app offers at most one
questionnaire per day (the daily one, or the weekly, monthly or EQ-5D-5L one on
the days it is due), so every type counts.

- **Window:** the 30 full days before today. Today is left out, so a patient who
  fills in this evening is not marked down this morning. The window never starts
  before the registration day.
- `days_expected`: number of days in the window (30, or fewer for a new patient;
  0 on the registration day).
- `days_with_entry`: days in the window with at least one questionnaire of any
  type. Two questionnaires on the same day count once. Step counts do not count.
- Always `0 ≤ days_with_entry ≤ days_expected ≤ 30`.

Example: registered 10 days ago and filled in something every day = 10 / 10.

### How the portal should load it

- Patient list: `getPatients?status=active` and `?status=inactive`, as today.
- Cohort overview: `getPatients?status=all&include=lars_history`, once, when the
  overview opens.

## Cost

Measured on a local copy with 305 visible patients and about a year of data each:

- List query (SQL only): about 9 ms → 14–18 ms. Still one database query for the whole list.
  Expect 2–3 times more on the shared Supabase server.
- List end to end (real app, 305 patients): about 16 ms → 50 ms, mostly building and
  encoding the larger reply; about 140 ms with `lars_history`. Fine for a doctor portal.
- List size: 112 KB → 335 KB raw, about 31 KB with gzip. With `lars_history`:
  734 KB raw, about 70 KB with gzip.
- Patient detail: one more database query (monthly answers); about 40–65 % larger
  before compression.

## Testing

```bash
python3 -m unittest discover -s tests -v
```

The unit tests need no database and no extra packages. The change was also checked
against a throwaway local Postgres 17 built from `schema.sql` and the migrations:
the real route code at the previous commit and at this commit gave identical
responses once the new keys were removed (list for 4 doctors × 3 statuses, 10 detail
calls including 403 and 404). All test data was invented.

## Security

Every request is authenticated with a verified Firebase ID token (signature, project,
expiry); see `src/services/firebase_auth.py`. The new fields stay inside the doctor's
existing access scope: same patients, same hospital check on the detail endpoint.

## Rollback

Revert this commit. The database is not touched, so there is nothing to undo
there. The new portal detects the new fields by their presence and falls back to
its "not available yet" states without them.
