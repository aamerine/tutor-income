# Tutor Income Planner

A small web app for modeling a private tutor's **gross revenue** across the school year and
summer. Enter each student's hourly rate, weekly hours (school year and summer separately) and
start/end dates; the charts and totals update as you type.

It shows:

- **Summary:** total revenue for the plan period, average per month against the target,
  average hours per week, and effective hourly rate, each split by school year and summer.
- **Target & time:** whether the current mix reaches the monthly target, how many hours a
  regular school week (and summer week) would take at her current average rate, and a slider:
  *"if she worked N hrs in a regular school week, what average rate would she need?"*
- **Charts:**
  - monthly revenue (school-year and summer portions stacked) against the target
  - weekly revenue and weekly hours across the whole year, with breaks visible as dips
  - revenue grouped by hourly rate
- **Students table:** each student's share of the total, plus a checkbox to see the plan
  without that student.

## Running it

Everything runs in containers. You need Podman (or Docker; set `ENGINE=docker`).

```sh
./run.sh start      # build and run at http://localhost:8080
./run.sh stop       # stop it (data is kept)
./run.sh logs
```

Options: `PORT=9000 ./run.sh start` changes the port. `BIND=0.0.0.0 ./run.sh start` makes it
reachable from other devices on your network (a phone, for example). There is no login, so
only do that on a network you trust.

**Starting on boot (rootless Podman):** the container uses `--restart always`. Podman's user
service restores such containers at login. To have it start at boot without logging in, run:

```sh
systemctl --user enable podman-restart.service
loginctl enable-linger "$USER"
```

Docker users can use `docker compose up -d --build` with the included `compose.yaml`.

## Data and backups

- The plan is stored in SQLite in the volume `tutor-income-data`. It survives container
  rebuilds and restarts.
- Every save is kept as a version: the newest 500 are retained in the `plan_versions` table,
  so an accidental change can be recovered.
- **Download backup** saves the plan as JSON, and **Restore backup** loads one. Older backups,
  from before summer dates existed, are converted when restored: summer becomes the day after
  school ends through one year after school started.
- `podman volume rm tutor-income-data` deletes all data.

## How the model works

She teaches all seven days, so a student's weekly hours are spread evenly across the week.
For each day in the plan period:

```
hours   = (school-year or summer hrs/week) / 7 × break factor
revenue = hours × rate
```

- The modeled year runs from **school start** to **summer end**. Days from school start to school
  end are **school year**, and days from summer start to summer end are **summer**.
- Summer must start the day after school ends, so every day belongs to exactly one season. In
  the app, changing school end moves summer start, and the other way around.
- A **break** sets the share of normal hours worked: 0% means fully off, 50% means half load.
  When breaks overlap, the lowest percentage wins. Breaks apply in any season, so a summer
  vacation is just another break.
- Student start and end dates are inclusive. A blank end date means the student continues.
- **Monthly target:** for partial months at the edges of the plan, the target is reduced in
  proportion to the days covered. The weekly "target pace" line is the monthly target × 12 / 365
  per day.
- **Effective rate** is total revenue ÷ total hours, so it is weighted by hours.
- **Regular week** hours are a season's hours ÷ its *working weeks*, where break days count by
  their percentage (a week fully off counts 0). Hours are always quoted per regular school or
  summer week, never averaged across the whole year. Averaging in summer and breaks makes her
  workload look lighter than it is (the "whole-year average" is shown only as a footnote).
- **Hours needed for the target:** every student's hours are scaled by the same factor
  (target ÷ revenue), so the rate mix stays the same.
- **Slider:** rate needed = target ÷ (N × school working weeks + planned summer hours).
- **Average per month** is normalized to a 365-day year.

This models gross revenue only: no taxes, expenses, cancellations or no-shows. The default
calendar is a typical US approximation: school runs from the 4th Monday of August to the 2nd
Friday of June, summer lasts until the day before the next school year, and there are
Thanksgiving, winter and spring breaks. Edit it to match the
actual district calendar.

## Development

```
app/
  model.py      projection engine (pure functions; all income math lives here)
  schemas.py    data shapes, validation rules, default calendar
  storage.py    SQLite persistence with version history
  main.py       FastAPI routes + static files
  static/       frontend (plain JS + Chart.js 4.5.1, vendored)
  static/fonts/ Fraunces + Nunito (SIL OFL, vendored from @fontsource-variable 5.3.0)
tests/
  unit/         model and validation tests
  integration/  API + storage tests against a real SQLite file
  e2e/          Playwright browser tests against a running container
```

```sh
./run.sh test       # unit + integration (pytest, in a container)
./run.sh e2e        # browser tests: starts a fresh app container and drives Chromium
./run.sh test-all
./run.sh test -k gap   # extra args go to pytest
```

On failure, e2e screenshots are written to `test-results/`.

API: `GET/PUT /api/plan`, `GET /api/projection`, `POST /api/projection` (preview without saving),
`GET /api/export`, `GET /api/health`.

**Dependencies:** direct dependencies are pinned in `requirements*.txt` and indirect ones in
`constraints.txt`. Versions were chosen to be at least two weeks old when added. The Playwright
version in `requirements-e2e.txt` must match the `Dockerfile.e2e` base image tag.

**Look & personalization:** the sage & cream theme lives in `app/static/styles.css` as CSS
variables, with a matching dark theme. The chart colors `--school` and `--summer` were checked
for colorblind safety against the card color in each theme, so re-check them if you change
them. Jessica's name appears in `index.html` (title, header, footer) and in the greeting in
`app.js`.
