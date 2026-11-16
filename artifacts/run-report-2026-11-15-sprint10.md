# Sprint 10 run report: TM05-169 and TM05-170 (2026-11-15)

Davis Stapleton's two Sprint 10 stories, built in one unattended run with Claude Code.
Both are merged with CI green. Both stories are still **In Progress** in Jira: no worklogs
were added and nothing was moved to Done, as instructed. Each story has a comment with its
PR link and a summary.

| Story | PR | Merged (UTC) | Merge commit | CI |
|---|---|---|---|---|
| TM05-169 Auto-plan overnight stops | [#133](https://github.com/dtstaple/campsite_454/pull/133) | 2026-11-16 03:30 | `aaa5d3a` | quality, frontend: pass |
| TM05-170 Natural-language trip finder | [#134](https://github.com/dtstaple/campsite_454/pull/134) | 2026-11-16 03:56 | `6936bbe` | quality, frontend: pass |

**Final gate on `main` at `6936bbe`:**
- `ruff check`, `ruff format --check` and `makemigrations --check` are clean.
- **pytest: 1,490 passed**, 10 deselected (the `network` and `data` markers).
- oxlint: 0 errors. `npm run build` succeeds. **npm test: 273 passed.**
- **`main`'s CI run on `6936bbe`: success.**

**Setup notes.**
- Docker Desktop wasn't running. It was started, and `docker compose up -d --wait` brought
  up `campsite_db`.
- One migration, `terrain.0004_terrainfacts_sun_hours`, was unapplied on the dev DB and
  was applied. `make doctor` then passed every check.
- No `docker volume prune` or `docker system prune` was run.

---

## TM05-169: auto-plan overnight stops

### Acceptance criteria

| AC | Met | Evidence |
|---|---|---|
| Given a route and N nights (or a daily mileage target), the app proposes stops from mapped campsites and potential spots | Yes | `POST /api/plans/auto/` (`backend/planning/autoplan.py`). Takes `nights` or `daily_target_m`, on a route, an assembled trail or a planned route. Mapped campsites come from the trail list's query; potential spots from Find campsites' cached search. Tests: `test_auto_plan_proposes_legal_stops_and_works_out_the_days`, `test_a_daily_target_sets_the_nights`. |
| Only "Permitted" stops are chosen automatically; a day with no legal stop is reported, not filled | Yes | Only `verdict == "permitted"` is eligible. A night with none in its window gets "No legal stop between mi 33.4 and mi 45.1 for night 2, so that night is left out…". Tests: `test_a_night_with_no_legal_stop_is_reported_and_never_filled`, `test_a_day_with_no_legal_stop_is_reported_not_filled`, `test_no_legal_stop_at_all_returns_no_plan`. Browser: Northville-Placid, 6 nights. |
| Stops balance daily distance and gain and prefer higher scores, with the weights in config | Yes | Exact dynamic programming over windowed stops. Weights are in `backend/planning/autoplan.yml` (distance 1.0, gain 0.5, score 0.3). Tests: `test_climb_is_balanced_too`, `test_a_higher_score_wins_when_the_days_are_as_even`, `test_balance_beats_a_slightly_higher_score_and_says_so`. |
| Each day shows its distance, gain and loss, and why that stop was chosen | Yes | Day table, plus a "Why here" row per stop. Reasons quote the table's own gain figures. Screenshots: `artifacts/tm05-169/*-days.png`. |
| Opens as a normal editable plan that can be saved and exported as GPX | Yes | The answer becomes an unsaved draft. In the browser on Phelps Trail: saved ("Plan saved."), GPX fetched (812 track points, 1 `overnight-stop`), then a night added by hand (reasons hide). Test: `test_the_proposal_saves_and_exports_as_a_normal_plan`. |
| Tests cover even splits, a day with no legal stop, a target distance, and a too-short route | Yes | `tests/test_autoplan.py`, 42 tests. Also determinism: `test_the_same_input_gives_the_same_plan` shuffles 80 stops, and `test_the_same_request_gives_the_same_plan` checks via the API. |

### Measurements (dev DB)

| Trail | Request | Mapped (Permitted) | Server time | Result |
|---|---|---|---|---|
| Northville-Placid Trail, 137.4 mi | 3 nights | 61 (52) | 575 ms | Days 30.4 / 33.6 / 37.9 / 35.5 mi; gains 3,914 / 3,613 / 3,349 / 2,920 ft |
| Northville-Placid Trail | 6 nights | 61 (52) | < 1 s | 5 stops; night 2 reported as a gap (mi 33.4–45.1) |
| Phelps Trail, 7.8 mi | 1 night | 22 (22) + 5 cached potential spots | 183–226 ms | Bushnell Falls Lean-to #1; days 4.8 / 3.0 mi |

**In the browser** (headless Chrome, 1440x900 and 390x844), from click to plan: 0.6 to 3.6
s. The first request per trail includes loading the trail's profile. There are 11
screenshots, listed in `artifacts/tm05-169/README.md`.

### Judgment calls
1. **Potential spots are never chosen.**
   - In this codebase a potential spot's verdict is always "Unknown" (`plans._candidate_legality`).
   - So only Permitted mapped campsites are chosen. Potential spots are counted in the gap
     message so a hiker can choose one by hand.
   - Auto-plan reads Find campsites' **cached** search only. It never starts the 15–35 s
     3DEP search.
2. **Method: windows plus exact dynamic programming.**
   - Night k's stop must lie within 30% of an even day of k × length / days. The windows
     never overlap, so the nights stay in order and a gap has a clear "between mi A and mi
     B".
   - Within that, the DP is exact.
   - The stops are fixed to these windows. A plan with very uneven days is never proposed;
     a gap is reported instead.
3. **Daily target.** Days = the count whose even split is closest to the target; ties go
   to the shorter days. A route that is one day at the target is refused, since it needs no
   stop.
4. **Too short.** Even days under 3 km (`min_day_m`) are refused with a sentence ("Choose
   fewer nights").
5. **Scores.** Stops are chosen on the default-weight score: the score the plan table shows
   (`build_plan` uses the shipped config), so the "why" matches the table. A signed-in
   user's personal weights don't affect the choice.
6. **Climb.** The DP sums every rise of the smoothed profile, so its climb measure is
   additive. The table and the reasons use the plan's own thresholded day gain. Both come
   from the same stored profile.
7. **No overwrite.** The result opens as a **new unsaved** draft. Saving never overwrites
   the plan that was open.
8. **Reasons hide after a hand edit.** Once the stops are changed by hand, the reasons no
   longer describe the plan, so they are hidden.

### Shared-file edits
- `backend/planning/plans.py` (Davis, TM05-81): moved the stop's score, verdict and name
  into a new `assess()`, so build_plan and auto-plan use one implementation. Behaviour
  unchanged; all 23 plan tests pass.
- `backend/planning/plan_views.py`, `backend/planning/urls.py`: the new view and route.
- `frontend/src/plans/PlanBuilder.tsx`, `plans/api.ts`, `plans/plans.css`: the Auto-plan
  control, the "Why here" rows, the gap list, and the API call.
- `docs/routing.md`, `docs/api.md`: new sections.

### Found, not fixed (outside the story)
- **Northville-Placid's trail detail returns 500 on the dev DB.**
  - `GET /api/routes/4286650/` fails in `terrain/along.py` (TM05-152, Sahaj Soni) with
    `GEOSIntersects: TopologyException: side location conflict`.
  - The dev DB has 100 invalid terrain-zone geometries (`ST_IsValid` false): damp-ground
    33, exposure 11, pooling-risk 15, sheltered 41.
  - **Not changed.** For the screenshots only, the dev server ran through a wrapper outside
    the repo that answers `terrain_along` as "unavailable" on that error (see
    `artifacts/tm05-169/README.md`).
  - **Suggested next step:** `ST_MakeValid` the zones on load, or in the query (owner's
    call).
- **"1 nights".** A saved plan with no name defaults to "<trail>: 1 nights"
  (`plan_views.plans_view`, pre-existing).

---

## TM05-170: natural-language trip finder

### Acceptance criteria

| AC | Met | Evidence |
|---|---|---|
| Free text on Discover goes to an LLM that returns ONLY schema-valid JSON of supported filters and weights; anything invalid is rejected | Yes (mocked; the live check is waiting on a key) | `backend/discover/interpret.py`: Anthropic SDK, structured outputs, `schema.validate()`. Tests: `test_valid_model_output_becomes_search_filters`, `test_the_request_is_capped_short_and_asks_for_json_in_the_schema`, and 17 parametrised rejections in `test_invalid_or_out_of_schema_output_is_rejected_and_the_keywords_take_over`. |
| Results always come from the existing trail search, never from the model | Yes | The response carries `search` (trail-search parameters). The page sets its own filters to them and runs `GET /api/routes/search/` as usual. The model never returns or ranks trails. |
| "How I read your request" appears as editable filter chips | Yes | `frontend/src/browse/TripFinder.tsx`. Solid filter chips (× removes; choosing one opens Filters) and dashed read-only chips. In the browser, removing "Moderate" changed the results from 51 to 108 trails. Screenshots in `artifacts/tm05-170/`. |
| Unsupported asks are named back to the user | Yes | "Crowding isn't something we can measure yet." / "Dog rules isn't…". Tests: `test_unsupported_asks_are_named_back`, plus the keyword-parser cases. Screenshot: `unsupported-asks-*.png`. |
| A keyword-parser fallback runs when no API key is set | Yes | `test_without_a_key_the_model_is_never_called`. Also runs on a timeout, an API error or invalid output (tested). The page shows a note when it ran. |
| The API key lives only in env vars, never committed or sent to the browser | Yes | It is read in `config/settings.py` from `ANTHROPIC_API_KEY`. `.env.example` has an empty placeholder. `test_the_key_never_reaches_the_browser`. A scan of `backend`, `frontend/src`, `docs`, `tests` and `.env.example` found no key, and the frontend has no reference to one. |
| Tests cover validation, rejection, the fallback, and unsupported asks (with the model mocked) | Yes | `tests/test_discover_interpret.py`, 49 tests, with no network. Also caching, throttling (429), bad requests and the keyword parser on 10 phrases. `frontend/tests/tripReading.test.ts` adds 7. |

### Live LLM check: not run, waiting on a key
`ANTHROPIC_API_KEY` is not set in this machine's `.env`, so no real model query was made,
and the 5 example interpretations could not be recorded. Every browser run used the keyword
parser, and the page said so. To run the check, set the key in `.env`, restart the backend,
and post the 5 queries to `/api/discover/interpret/`. The response's `source` will read
`llm`.

### Measurements (keyword parser, dev DB, Adirondack Park: 270 trails)

| Request | Reading | Trails |
|---|---|---|
| "two nights, lakeside, moderate climb" | moderate · campsites within 500 m · 2 nights · water view | 51 |
| the same, "Moderate" chip removed | campsites within 500 m · 2 nights · water view | 108 |
| "quiet overnight in the High Peaks, dog friendly, under 12 miles" | Adirondacks · under 12 mi · campsites within 500 m · 1 night; unsupported: crowding, dog rules | 101 |

From click to chips took 305–322 ms at both sizes (1440x900 and 390x844).

### Judgment calls
1. **"Discover" means the Discover trails page** (`/trails`, `pages/BrowseTrails.tsx`).
   That is the header's "Discover trails", the region browser of TM05-102. It has the
   region, filters and sort the schema maps to, and the map page's floating search is tied
   to the map view.
2. **The schema is the trail search's real filters.**
   - Length, gain, difficulty, route type, campsites within 500 m and region all filter.
   - **Nights, water view, sheltered and weights are read and shown, but are not trail
     filters.** Water view and sheltered are campsite facts. Applying weights would change
     the user's saved scoring.
   - They are dashed chips that say so.
   - One night or more adds "campsites within 500 m", unless the hiker said no campsites.
3. **"Easy access" has no field.** Road distance isn't measured anywhere in CampSite. So the
   schema leaves it out, and the prompt and the keyword parser name it back as unsupported
   ("easy access from the road").
4. **Model settings.**
   - `max_tokens` 500, a timeout of 8 s, no retries.
   - Thinking is disabled and effort is `low`, so the token cap goes to output. Haiku 5.5
     accepts disabled thinking at effort `high` or below.
   - The request text is wrapped in `<request>` tags and treated as data.
5. **Validation goes beyond the schema sent.** Structured outputs can't express numeric
   ranges or string lengths, so `schema.validate()` enforces all of them. Output that
   breaks a rule is rejected, not repaired.
6. **Caching.**
   - Identical requests are cached for 10 min. The key covers the normalised text, the
     model, the schema version, and whether a key is set.
   - A transient failure (timeout, API error, invalid output) is never cached.
7. **Throttle.** `ScopedRateThrottle`, scope `discover-interpret`, 20 requests a minute per
   IP, reusing the TM05-88 setup and its readable 429 message.
8. **The keyword parser never guesses.** It sets no weights, and no region unless exactly
   one is named. "Weekend" means 2 nights; "a 10 mile hike" means 8–12 mi; "flat" means
   under 500 ft.
9. **SDK.** `anthropic==2.8.0`, the official Python SDK. It was installed in the venv and
   pinned in `requirements.txt`.

### Shared-file edits (minimal)
- `backend/config/settings.py`: one throttle rate; five env-backed settings
  (`ANTHROPIC_API_KEY`, `DISCOVER_LLM_MODEL`, `DISCOVER_LLM_TIMEOUT_S`,
  `DISCOVER_LLM_MAX_TOKENS`, `DISCOVER_INTERPRET_CACHE_S`); and one comment line updated
  for the new throttle.
- `backend/config/urls.py`: one `include("discover.urls")`.
- `backend/accounts/throttling.py` (Abdulrahman Shaalan, TM05-88): one scope constant and
  its 429 message.
- `requirements.txt`: one pin, `anthropic==2.8.0`.
- `.env.example`: a documented section with an empty `ANTHROPIC_API_KEY=` and the other
  variables commented with their defaults. Placeholders only.
- `frontend/src/pages/BrowseTrails.tsx`, `frontend/src/browse/browse.css`: mount the
  finder, apply its reading, and its styles (theme tokens only).
- `docs/api.md`: new section.

### Env vars to set (names only)

| Variable | Needed | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | For the model reader; without it, the keyword parser | empty |
| `DISCOVER_LLM_MODEL` | No | `claude-haiku-5-5` |
| `DISCOVER_LLM_TIMEOUT_S` | No | `8` |
| `DISCOVER_LLM_MAX_TOKENS` | No | `500` |
| `DISCOVER_INTERPRET_CACHE_S` | No | `600` |
| `DISCOVER_INTERPRET_RATE` | No | `20/min` |

---

## Housekeeping
- **The uncommitted local `.env.example` was preserved.**
  - The working tree started with a local modification to `.env.example` (an older,
    shorter version), plus untracked `artifacts/sprint8-plan.md` and `docs/mobile-plan.md`.
    None of them were committed.
  - The TM05-170 commit was built from `HEAD`'s `.env.example` plus the new section. The
    local copy was put back afterwards, byte for byte, so `git status` still shows it as
    modified.
- **A local check user exists.** `browsercheck` (unusable password, with a token) was
  created in the dev DB for the signed-in browser runs, along with the Phelps Trail plans it
  saved. It is local only.
- **No branch was stacked or force-pushed.** Each story branch was cut from an up-to-date
  `main`.
