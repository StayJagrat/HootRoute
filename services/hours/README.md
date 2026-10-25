# Streetwise hours-evidence pipeline

492 of 878 OSM places in the downtown pilot area have no `opening_hours`, so the engine counts them as closed.
This module fetches Google Maps opening hours (via Apify), matches them to OSM places, converts them to OSM
`opening_hours` syntax the engine's `is_open` can read, and writes one evidence file the engine ingests.

```
fetch_apify.py ──> data/cache/hours_raw_*.json
match_osm.py   ──> data/cache/hours_matches_{real,mock}.json
parse_hours.py ──> data/cache/hours_evidence.json   (mock: hours_evidence.mock.json)
evaluate.py / make_handlabel_template.py / score_handlabels.py   (measure it)
run_pipeline.py runs all of it
```

## Setup

```bash
cd /Users/aryabhatt/Documents/GitHub/StreetWise
python3 -m venv .venv-hours && .venv-hours/bin/pip install -r services/hours/requirements.txt   # venv already created
cp services/hours/.env.example services/hours/.env     # then fill in keys (.env is git-ignored)
```

Nothing here writes outside `services/hours/` and `data/cache/`, and nothing touches the engine. The engine's own
`is_open` is imported from `services/engine/streetwise_engine/world.py` (needs numpy + networkx, both in requirements;
if they are missing the function is compiled straight out of `world.py` via `ast`, never copied).

## Try it offline (no keys)

```bash
cd services/hours
../../.venv-hours/bin/python run_pipeline.py --mock       # fetch -> match -> parse -> evidence -> eval + hand-label CSV
../../.venv-hours/bin/python -m unittest discover -s tests
```

`--mock` synthesizes "Google" records from real OSM places (name variants, 0-20 m jitter, wrong-branch chain decoys,
Google-only places, messy hours strings, ~10% deliberately stale hours). All mock output is labelled `mock:` in `source`
and goes to `hours_evidence.mock.json`, never to the real file. **Mock accuracy numbers only prove the plumbing; the pitch
number must come from a real run.**

## The stages

| Stage | Command | Notes |
|---|---|---|
| 1 fetch | `python fetch_apify.py [--categories a,b] [--tiles 2] [--budget-usd 10] [--refresh] [--dry-run] [--mock]` | one Apify run per category (x tile). Polygon from `data/cache/bbox.json` (+0.0005 deg pad), `[lng, lat]`, closed ring. `maxCrawledPlacesPerSearch` 300, `language en`, `skipClosedPlaces false`. Cost cap: `max_total_charge_usd` per run (`--per-run-cap-usd`, default 2) and a cumulative `--budget-usd` (default 10, env `HOURS_APIFY_BUDGET_USD`). Cached per category in `data/cache/hours_raw_<category>.json`; re-runs skip cached files. `--dry-run` prints the exact inputs. |
| 2 match | `python match_osm.py [--max-m 30] [--min-sim 0.72]` | pair must be <= 30 m AND name similarity >= 0.72 (difflib on normalised names + token-subset rule); one-to-one greedy by confidence. Same-name branches farther away never match; unnamed OSM places never match. |
| 3 parse | `python parse_hours.py [--parser rules\|claude\|auto] [--only-missing]` | `rules` = offline regex parser (default with `--mock`); `claude` = every string goes to Claude (`claude-haiku-5-5`, override `HOURS_CLAUDE_MODEL`), cached in `data/cache/hours_parse_cache_claude.json`; `auto` (default for real runs) = rules first, Claude only when rule confidence < 0.9 or no parse. No source text -> `null`, never a guess. Every output must pass `validate_osm_hours` (strict grammar + engine round trip over all 336 half-hours) or it is dropped. |
| eval | `python evaluate.py [--mock] [--n 40] [--seed 7] [--all] [--parser ...]` | see below |
| hand labels | `python make_handlabel_template.py` then `python score_handlabels.py --csv handlabel_template.csv` | 40 places, columns `place_id,name,address,our_hours,verified_hours,verified_by,notes`. Fill `verified_hours` (OSM syntax, or plain text like `Mon-Fri 9am-5pm, Sun closed`, or `closed`). |

## Output schema (`data/cache/hours_evidence.json`)

```json
{"n298086258": {"opening_hours": "Mo-Th 11:00-21:30; Fr 11:00-23:00; Sa 17:00-02:00; Su off",
                "confidence": 0.9, "source": "apify:google_maps", "fetched_at": "2026-10-24T18:02:22+00:00",
                "raw": "Monday: 11 AM to 9:30 PM; ...", "matched_name": "Starlite Room", "distance_m": 12.0}}
```

* Keys are engine place ids (`n123` / `w456`). Only places with a non-null parsed value appear.
* `confidence = parse_confidence * (0.8 + 0.2 * match_confidence)`.
* `source`: `apify:google_maps` (rules parser) or `claude:parsed`; `mock:` prefix on mock runs.
* `opening_hours` can be `"off"` when Google flags the place permanently/temporarily closed.
* Evidence is written for every matched place, including ones that already have OSM hours (Google may disagree). Use `--only-missing` to restrict to the 492 gaps.

## Evaluation (the pitch number)

`evaluate.py` samples N=40 places that have BOTH a trustworthy OSM `opening_hours` and a fetched source text, runs only
the parse stage on the source text, and compares parsed vs OSM with the engine's `is_open` on every 30 minutes of the week
(336 slots). It reports (a) mean % of slots that agree, (b) % of places with >= 95% agreement (with a 95% Wilson interval),
(c) null count, exact-string matches, a per-shape breakdown, and the baseline "no hours = always closed" for contrast.
Disagreement mixes parser errors with genuine OSM-vs-Google differences; on real data they cannot be separated, so
phrase it as "agreement with OSM-listed hours", and use the hand-label CSV for true accuracy. `--all` evaluates every eligible place.

## Real run (human steps)

1. Create an Apify account, redeem coupon `APIFY_CAL_HACKS` ($200 credit), copy the API token (Console > Settings > Integrations).
2. Create an Anthropic API key. Put both in `services/hours/.env` or export `APIFY_TOKEN`, `ANTHROPIC_API_KEY`.
3. `cd services/hours && ../../.venv-hours/bin/python run_pipeline.py --dry-run` (check inputs and the estimate).
4. Smoke test: `... fetch_apify.py --categories pharmacy` (about $0.50-1), open `data/cache/hours_raw_pharmacy.json`, confirm `openingHours` is a list of `{day, hours}` per item. If `openingHours` is missing, re-run with `--detail-page --refresh`.
5. `... run_pipeline.py` (add `--tiles 2` if restaurant/bar results hit the 300 cap). Then `... evaluate.py --parser claude --n 40` for the Claude number.
6. Hand-verify the 40 rows in `handlabel_template.csv` (phone or walking), then `score_handlabels.py`.

**Expected cost:** Apify is pay-per-event, $0.004 per place on the free tier. 12 default categories x up to 300 places is
at most about $14 in the worst case; the default `--budget-usd 10` stops launching runs at $10. Typical total is roughly
$7-10 of the $200 credit. Claude Haiku parsing of about 700 short strings is well under $1 (`auto` mode calls it for only a fraction).

## Google Maps terms-of-service caution

Google Maps content is subject to Google's terms. Keep only the *derived* hours values (not reviews, photos, ratings, or
bulk place records), label the origin as **"Google Maps via Apify"** wherever it is shown, and use it for the demo corridor
only. Do not republish the raw cache (`hours_raw_*.json` stays local; it is under `data/cache/`, check it is git-ignored
before committing).

## Notes for the engine side

* `is_open` treats unlisted days as closed (returns `None`, `bool(None)` is False), so partial schedules are safe.
* `is_open` truncates end times above 24:00 (`Th-Sa 18:00-26:00` loses the after-midnight hours) and ignores `PH` and `16:00+`. The pipeline never emits those forms and ignores them as ground truth (about 59 matched OSM values, mostly these odd forms, are excluded from the eval).
* Prefer OSM hours when present unless you decide Google is fresher; both are in the evidence file.
