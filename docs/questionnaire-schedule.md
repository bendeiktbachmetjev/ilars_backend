# Questionnaire schedule: which questionnaire a patient gets today

This page describes how the backend decides which questionnaire the app shows a
patient on a given day (`GET /getNextQuestionnaire`). The mobile app and the web
app both use this endpoint, so the rules are the same everywhere.

Code: [`src/services/questionnaire_schedule.py`](../src/services/questionnaire_schedule.py) ·
Tests: [`tests/test_questionnaire_schedule.py`](../tests/test_questionnaire_schedule.py)

## In short

- **At most one questionnaire per day.**
- **The daily questionnaire is the default.** The weekly (LARS), monthly and
  EQ-5D-5L questionnaires *replace* the daily one on the days they are due.
- **Missed questionnaires never pile up.** After a break, each questionnaire that
  is due comes back **once**, one per day, rarest first. Then the daily ones continue.
- **Missed daily questionnaires are lost.** There is no catching up on past days.

## The four questionnaires

| Type in the API | Name in the app | When it is due |
|---|---|---|
| `eq5d5l` | Quality of life questionnaire (EQ-5D-5L) | At 6 time points: the registration day, then 14, 30, 90, 180 and 365 days after registration |
| `monthly` | Monthly questionnaire | 28 days after the last monthly one (right away if never filled) |
| `weekly` | Weekly questionnaire (LARS) | 7 days after the last weekly one (right away if never filled) |
| `daily` | Daily questionnaire | Every day when nothing else is due |

"Registration day" is the day the doctor created the patient code
(`patients.created_at`), not the day the patient first opened the app.

## How today's questionnaire is chosen

**Step 1. Has the patient already filled any questionnaire today?**
If yes, nothing more is offered today. The response says which one was filled
(`today_filled_type`), so the app can show "Completed" and an "Edit today's
answers" button.

**Step 2. Otherwise, check in this order and offer the first one that is due:**

1. EQ-5D-5L
2. Monthly
3. Weekly
4. Daily (always available)

Rarer questionnaires go first because missing one of them costs more data. A
weekly questionnaire that waits a day or two loses very little.

### Weekly and monthly

Only the date of the **last** fill matters. If the weekly questionnaire was last
filled 5 weeks ago, it is due *once*, not five times. After it is filled, the next
one is due 7 days later. The monthly one works the same way with 28 days.

If a weekly or monthly questionnaire is due on a day that is taken by a
higher-priority one, it simply moves to the next day the patient opens the app.

### EQ-5D-5L

- Time points: day **0, 14, 30, 90, 180, 365** after registration.
- It is due **on** the time point day.
- On any day, only the **latest time point that has already arrived** matters.
  Older missed time points are dropped: one late questionnaire covers them all.
- A time point counts as **done** if an EQ-5D-5L was filled **on or after 7 days
  before it**. So a late questionnaire filled shortly before the next time point
  also covers that next time point. As a result, two EQ-5D-5L are never offered
  less than 8 days apart.
- After the 365-day time point is done, EQ-5D-5L is not offered any more.

## Examples

Day numbers are days after registration (day 0 = the day the code was created).

**A. New patient who opens the app every day.** Days not listed get the daily questionnaire.

| Day | 0 | 1 | 2 | 9 | 14 | 16 | 23 | 29 | 30 | 31 | 38 | … | 90 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Questionnaire | EQ-5D-5L | monthly | weekly | weekly | EQ-5D-5L | weekly | weekly | monthly | EQ-5D-5L | weekly | weekly | … | EQ-5D-5L |

On day 30 the weekly questionnaire was due too, but EQ-5D-5L took the day, so the
weekly one moved to day 31.

**B. Patient away for 3 months.** Active until day 60, back on day 151:
day 151 EQ-5D-5L (for the missed 90-day time point) → day 152 monthly → day 153
weekly → daily from day 154. Next weekly on day 160, next EQ-5D-5L on day 180.

**C. Code given long before first use.** The doctor created the code on day 0,
the patient first opens the app on day 40: day 40 EQ-5D-5L (one questionnaire
covers the missed day-0, 14-day and 30-day time points) → day 41 monthly → day 42
weekly → daily. Next EQ-5D-5L on day 90.

**D. Back just before a time point.** The patient missed the 30-day time point
and comes back on day 86. EQ-5D-5L on day 86 also counts for the 90-day time point
(it is within 7 days before it), so nothing extra on day 90. If they come back on
day 82 instead, they get EQ-5D-5L on day 82 and again on day 90.

**E. The problem these rules fixed (October 2026).** Under the old rules an
EQ-5D-5L time point counted as done only if the questionnaire was filled in a
narrow window (3 days before to 7 days after it). A late questionnaire never
counted, so a missed time point stayed "open" forever. A test patient registered on
2025-11-11 missed the 180-day time point; from 17 August to 3 October 2026 the app
offered EQ-5D-5L on every visit (7 times in a row, including two days running) and
never offered the weekly, monthly or daily questionnaire. With the new rules the
EQ-5D-5L filled on 17 August covers the 180-day time point, and the next one is
due on 2026-11-11.

## What "today" means

- "Today" is the **database date (UTC)**: the same clock that dates saved answers
  when the app does not send a date (`CURRENT_DATE` in the `send*` endpoints). This
  keeps "already filled today" consistent with how answers are stored.
- So one "day" runs from midnight UTC to midnight UTC. In Lithuania that is
  02:00 → 02:00 in winter and 03:00 → 03:00 in summer.
- The **mobile app** does not send a date; the server dates the answer.
- The **web app** sends the browser's local date (`entry_date`). In Lithuania,
  between local midnight and 02:00/03:00, this date is one day ahead of the
  server's date. An answer dated after "today" still counts as filled today, so
  the patient does not get a second questionnaire that night.

## Edge cases

| Situation | What happens |
|---|---|
| No questionnaires filled for months | One per day: EQ-5D-5L (if a time point has passed), then monthly, then weekly, then daily |
| Patient opens the questionnaire but does not finish it | The same questionnaire is offered again, also later the same day |
| Patient wants to correct today's answers | `today_filled_type` tells the app which one; saving again overwrites today's answers |
| Two questionnaires saved on the same day (old day-1 rule, or a direct API call) | Nothing more today; `today_filled_type` is the higher-priority one |
| Weekly and monthly due on the same day | Monthly today, weekly the next day |
| Patient code not in the database yet | EQ-5D-5L with a welcome message; the patient row is created with the first saved answer |
| More than one year after registration | No more EQ-5D-5L; weekly, monthly and daily continue |
| Patient status set to inactive or dead by the doctor | Not taken into account (see open questions) |

## Open questions and possible improvements (not implemented)

1. **Patient's own local day.** For patients far from UTC the day changes at an
   odd hour: at Mayo Clinic (US Central time) it changes at 18:00–19:00 in the
   evening, about when the app's 19:00 reminder fires. Fix: both apps send the
   device's local date (for example an `X-Local-Date` header) and the server uses
   it for "today" and for dating answers. Needs a new mobile app release.
2. **Inactive or dead patients.** Should the app stop offering questionnaires
   when the doctor changes the patient's status?
3. **After one year.** Should EQ-5D-5L continue, for example once a year?

## API

`GET /getNextQuestionnaire`, header `X-Patient-Code: <code>`.

| Field | Meaning |
|---|---|
| `status` | `"ok"` (or `"error"` with `detail` on failure) |
| `questionnaire_type` | `"eq5d5l"`, `"monthly"`, `"weekly"`, `"daily"`, or `null` when today's questionnaire is already done |
| `is_today_filled` | `true` if the patient already filled a questionnaire today |
| `today_filled_type` | Which questionnaire was filled today (for "Edit today's answers"), otherwise `null` |
| `reason` | Short English text; the mobile app shows it under the questionnaire name |

Examples:

```json
{"status": "ok", "questionnaire_type": "weekly", "is_today_filled": false,
 "today_filled_type": null, "reason": "Weekly questionnaire due"}

{"status": "ok", "questionnaire_type": null, "is_today_filled": true,
 "today_filled_type": "monthly", "reason": "You have already completed a questionnaire today."}
```

## Changing the rules

- Intervals, time points and priority are constants at the top of
  `src/services/questionnaire_schedule.py`.
- The endpoint (`src/routes/questionnaire.py`) only loads today's date and the
  last fill date of each questionnaire in one query, then calls `pick_questionnaire`.
- Run the tests from the `backend` folder (no database or extra packages needed):

  ```bash
  python3 -m unittest discover -s tests -v
  ```

  Besides fixed scenarios, one test replays 300 random patterns of app use over
  900 days and checks the basic guarantees (one per day, no repeats too close
  together, nothing skipped).
- Update this page and the tests together with the code.

## History

**2026-10-03.** Rules rewritten:

1. EQ-5D-5L: late questionnaires now count; only the latest time point matters;
   due on the time point day (was 3 days before); a questionnaire filled up to
   7 days before a time point counts for it. Fixes EQ-5D-5L being offered every day.
2. Removed the "fill all four questionnaires on day 1" rule: one per day from the
   first day. (The mobile app already showed only one on day 1; the web app
   allowed four.)
3. "Today" now comes from the database clock instead of the server's clock, so it
   always matches the date the server gives to saved answers.
4. Answers dated after "today" (web app, after local midnight) count as today's.
5. Rules moved into a separate module with unit tests.
