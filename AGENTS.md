# Agent guide: Tutor Income Planner

This web app models a private tutor's **gross revenue** over one school year plus the summer
after it. The tutor is Jessica, and the app's UI is personalized for her. The repo owner is her
partner, who maintains the app with coding agents. `README.md` is the human-facing overview;
this file covers what you need to run, change and verify the app safely.

## Ground rules

- **Containers only.** Don't install Python, Node, or other toolchains on the host. Build,
  test and run everything through `./run.sh`. The machines this runs on are listed under
  "Machines" below.
- **Real data lives in the Podman volume `tutor-income-data`.**
  - Before any change to schemas, storage, or anything else that touches saved plans, back the
    plan up first:
    `curl -s localhost:8080/api/export -o data/backup-$(date +%Y%m%d-%H%M%S).json`
  - Never remove that volume.
  - Never commit `data/`, `*.db`, or exported plans. All of them are gitignored, and the repo
    may be public.
- **Collaborate.** The owner wants to be asked about design decisions and to get
  recommendations. Ask before changing behavior the owner chose; the "Domain rules" section
  lists those decisions.
- **Verify, don't assume.** Check package versions, release dates, calendar facts and math
  against a source or an independent calculation. Several bugs in this project's history came
  from plausible-looking assumptions.
- **Git:** the repo is public at https://github.com/aamerine/tutor-income. Only the owner's
  machine can push (it has the owner's SSH key, and commits use `aamerine <aamerine@users.noreply.github.com>`).
  Jessica has no GitHub account, so on her Mac pull updates with `git pull`, and commit locally
  only if asked. Never push without being asked.

## Machines

| | Owner's machine | Jessica's MacBook Pro (M5, Apple Silicon) |
|---|---|---|
| OS | Fedora Linux, SELinux enforcing | macOS |
| Engine | rootless Podman (no Docker, no compose provider) | Docker Desktop (recommended) or Podman via `podman machine` |
| Architecture | x86_64 | arm64 |
| Autostart | `podman-restart.service` restores `--restart always` containers | Docker Desktop's "Start when you sign in"; the container then restarts by itself |

**First-time setup on her Mac:**
1. Docker Desktop (`brew install --cask docker-desktop`; the old `docker` cask no longer exists).
2. `git clone https://github.com/aamerine/tutor-income.git`
3. `./run.sh start`
4. Her real data lives in the volume on whichever machine runs the app. To move it, use
   **Download backup** in the app on the old machine and **Restore backup** on the new one.

**Portability rules. Changes must keep working on both machines:**
- **bash 3.2.** `run.sh` runs under macOS's bash 3.2 with `set -u`.
  - Expand possibly-empty arrays as `${arr[@]+"${arr[@]}"}`; a plain `"${arr[@]}"` crashed
    under Docker on macOS.
  - No `declare -A`, `mapfile`, `${var,,}`, or other bash 4+ features.
  - No GNU-only flags: `sed -i` without a suffix, `date -d`, `readlink -f`.
  - To check, run the script under `docker.io/library/bash:3.2` with a stub `docker` on `PATH`.
- **SELinux `:Z`.** Bind-mount relabeling (`:Z`) is applied only when `selinuxenabled` succeeds.
- **arm64 images.** Every image must be published for both amd64 and arm64. Verify with
  `podman manifest inspect` / `docker manifest inspect`.
- **arm64 wheels.** Every Python dependency must be pure Python or have a `manylinux` aarch64
  wheel for the image's Python version (3.13 in the app images, 3.12 in the Playwright image).
  Otherwise the build would need a compiler.

## Commands

| Command | What it does |
|---|---|
| `./run.sh start` | Build the runtime image and (re)start the app on http://localhost:8080 with the data volume. This is also how you redeploy. |
| `./run.sh stop` / `logs` | Stop the app (data is kept) / follow its logs |
| `./run.sh test [pytest args]` | Unit + integration tests in the `test` image stage |
| `./run.sh e2e [pytest args]` | Playwright browser tests against a fresh app container (no volume) |
| `./run.sh test-all` | Both. **Run this before calling any change done.** |

- **Environment variables:** `PORT` (default 8080), `BIND` (default 127.0.0.1; there is no
  auth, so use 0.0.0.0 only on a trusted LAN), `ENGINE`.
- **Startup on boot:** the container uses `--restart always`. On Fedora, that is the only
  policy `podman-restart.service` restores at boot.

## Architecture

```
app/model.py     project(plan) -> dict. All income math. Pure, no I/O.
app/schemas.py   Pydantic models (extra="forbid"), validation, legacy upgrade, default_plan()
app/storage.py   SQLite, append-only plan_versions table (newest 500 kept), WAL
app/main.py      FastAPI factory create_app(db_path); run with `uvicorn --factory`
app/static/      index.html, app.js (plain JS, no build step), styles.css,
                 vendor/chart-4.5.1.umd.min.js, fonts/ (Fraunces + Nunito, OFL)
tests/unit       model + schema tests     tests/integration  API + SQLite
tests/e2e        Playwright (separate image: Dockerfile.e2e)
```

**API:**

| Endpoint | Purpose |
|---|---|
| `GET /api/plan` | The saved plan, or a default plan with `saved_at: null` (the default is not saved) |
| `PUT /api/plan` | Validate, save a version, return `{plan, saved_at, projection}` |
| `GET /api/projection` | Projection of the saved plan |
| `POST /api/projection` | Preview a plan's projection without saving |
| `GET /api/export` | Download the plan as a JSON attachment |
| `GET /api/health` | Health check |

**Live updates (the owner asked for this; there is no Save button):**
1. Every input is validated client-side.
2. If valid, the client sends a debounced `PUT /api/plan` after 300 ms. Stale responses are
   discarded by a sequence number, and a request still in flight is aborted.
3. The PUT response's projection redraws the tiles, the charts and the computed columns in the
   student table. Form inputs are never re-rendered from a response, so focus is preserved.
4. A pending save is flushed on `pagehide` with `keepalive`.

## Domain rules (invariants; don't change these without the owner)

- **Calendar:** the plan runs from `school_start` through `summer_end`. `summer_start` must
  equal `school_end + 1 day`, so gaps and overlaps are rejected. The owner chose "not allowed"
  over treating gap days as days off. The UI links the two fields: editing one moves the other.
- **Daily model:** `hours = weekly_hours(season) / 7 × break_factor` and
  `revenue = hours × rate`.
  - She teaches 7 days a week.
  - Breaks apply in both seasons; overlapping breaks use the lowest factor.
  - All date ranges are inclusive.
  - Round only on output (`_r2`), so the roll-ups agree.
- **Monthly target:** reduced in proportion for partial months at the plan edges. The weekly
  "target pace" line is `monthly × 12 / 365` per day.
- **Hours are always quoted per regular week of a season.** A regular week means
  `season hours / working_weeks`, where `working_weeks` is the sum of the break factors over the
  season's days, divided by 7.
  - **Never average hours over all 52 weeks in user-facing text or math.** That was a real
    bug: averaging summer and breaks in, the what-if slider showed $46.03/hr where $63.64/hr
    was needed. The whole-year average appears only as a footnote.
  - Hours needed to reach the target: scale every season by `hours_scale_to_target`
    (target ÷ revenue), which keeps the rate mix unchanged.
  - Slider: `required rate = target / (N × school.working_weeks + summer.hours)`.
- **Schema changes need an upgrade path.** Old backups and DB rows exist. `Settings._upgrade_v1`
  converts the old `plan_start`/`plan_end` shape, and any future change needs a similar
  before-validator plus tests covering both the DB load and a backup restore.

## Frontend notes

- **Wording:** the UI speaks to Jessica as "you". Her name appears in `index.html` (title,
  header, footer) and in `greet()` in `app.js`.
- **Theme:** sage & cream. Tokens are defined on `:root` in `styles.css`, and the dark values
  appear in **two** blocks (the `prefers-color-scheme` media query and `[data-theme="dark"]`).
  Keep those blocks identical.
  - `--school` and `--summer` passed a colorblind-safety validator against `--surface` in each
    theme (light `#4a8640`/`#d39a2c`, dark `#3a8556`/`#bf8a2a`). Re-validate if you change them.
  - All text tokens meet WCAG AA contrast.
- **Charts:** Chart.js reads colors and fonts from the CSS variables in `theme()`.
  - The charts are rebuilt on theme change and after `document.fonts.ready`, because canvas
    text doesn't reflow when web fonts arrive.
  - Never put two y-axes on one chart. Hours and revenue each get their own chart.
- **Gotcha (canvas sizing):** when you change a `.chart-box` height, call `chart.resize()`
  right away. Otherwise the old canvas size lingers and can cover the next card. That happened
  and blocked the "Add student" button; `.chart-box` also has `overflow: hidden` as a guard.
- **Element ids** (`#t-revenue`, `#gap-summary`, `#whatif-*`, `#jar-*`, `data-key`/`data-field`
  attributes) are used by the e2e tests, so rename them together.

## Testing

- **Unit tests** (`tests/factories.py`) use a 365-day calendar: school 2026-08-24 to 2027-06-11
  (292 days), then summer to 2027-08-23 (73 days). 7 hrs/week = 1 hr/day, which makes expected
  values easy to derive by hand.
  - **Derive expected values by hand,** and say how in a comment. Never copy them from the
    model's output.
- **e2e tests** reset state through `PUT /api/plan` in the `seed` fixture. They run in their
  own network with a fresh, volume-less app container.
  - **Gotcha:** never name the app container or host `app`. Chromium forces HTTPS for `.app`
    hosts, which causes `ERR_SSL_PROTOCOL_ERROR`.
- **Sample data:** `examples/sample-plan.json` is placeholder demo data (no real students). A
  test restores it and checks the yearly total, so update both together. If the schema changes,
  regenerate it from `GET /api/export` after loading it.
- **Visual changes:** look at the page, don't trust tests alone. Screenshot it from the e2e
  image with Playwright at 1280 px and 400 px wide, in both color schemes, and check that
  `scrollWidth` equals the viewport width.

## Dependencies

- **Pinning policy:** pin exact versions that were released **at least two weeks before** you
  add them, and confirm arm64 support (see "Portability rules" above). Check release dates at `https://pypi.org/pypi/<pkg>/json` and, for npm fonts,
  `https://registry.npmjs.org/<pkg>`.
  - Direct dependencies go in `requirements*.txt`; indirect ones go in `constraints.txt`, which
    every requirements file references with `-c`.
  - After adding a package, regenerate the constraints from `pip freeze` in the built images,
    then re-check the release dates.
- **License:** the project is GPL-3.0-or-later. New dependencies and vendored files must be
  GPLv3-compatible: MIT, BSD, Apache-2.0, OFL (for fonts) and LGPL are fine, while GPLv2-only
  and proprietary code are not. Note any bundled file's license in the README's License section.
- **Playwright:** the version in `requirements-e2e.txt` must match the tag of the
  `Dockerfile.e2e` base image (currently 1.63.0).
- **Starlette TestClient** uses `httpx2`, not `httpx`.
- **Vendored files:** a test checks the sha256 of Chart.js. The fonts come from
  `@fontsource-variable/*@5.3.0`, and their licenses are in `app/static/fonts/`.

## Ideas discussed but not built

- Rate-raise scenarios, and "drop the lowest-paying students": the owner skipped both at first.
  They are the most direct way to model getting her time back.
- A "months of cushion" figure for the summer dip.
- Phone access over the LAN (`BIND=0.0.0.0`, no auth).
