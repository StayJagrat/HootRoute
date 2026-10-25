# Routing corrections on Final_Edit

The existing seven score weights and all frontend, UI, UX, design and assets are unchanged. Scores may change because distances, arrival weekdays, length weighting and help-point evidence are corrected. Previous demo scores must be recomputed.

## Correctness

- Opening hours advance to the arrival weekday across midnight and Sunday/Monday. Transit also checks the previous GTFS service day, including departures written as 24:10.
- Samples represent their actual lengths. Longest gaps and their start/end distances use those lengths. Lighting, main-road, transit and help coverage are weighted by distance, so densely mapped short edges do not distort the average.
- A shop's hours are checked at each encountered minute; one open observation is not spread to later encounters after closing.
- Police, fire stations and hospitals are no longer assumed continuously open. Help-access credit requires listed hours, an explicitly mapped public entrance, and a connection within 30 m of the walking graph. Distances then follow that graph. Missing entrance or hours data remains unknown; station schedules alone do not establish staffed help access.
- Corrected reference distributions use versioned cache files, so old gap calculations cannot silently calibrate the new score.
- UTF-8 file reads and portable clock formatting support Windows. Explicitly empty process variables disable provider integrations even when a local `.env` contains keys.

## Evidence and recommendations

- Missing or stale hours near the longest gap are prioritized for investigation. Paid checks still require approval. Failed checks do not invent hours.
- New listing results can refresh older listing evidence without overwriting OSM hours. Recent completed checks can restore evidence after restart without another paid run. Source times and run identifiers are retained.
- Search includes bounded alternatives using expected-arrival conditions and penalties for reusing the same streets. A* costs remain at least geometric length. Recommendations are the best searched candidates, not a guarantee of a global optimum.
- `POST /api/plans` and `POST /api/walks` accept optional `maxExtraMinutes` (0–120) and `maxGapM` (0–10000). Omission retains the existing 25% detour limit and no hard gap limit. Impossible requests return 422 rather than silently ignoring a limit. Use the same limits when starting the reviewed plan. Re-scoring, recovery and restored route records retain them.
- `meetsLimits`, `routingLimits`, `evidenceCoverage` and help-point evidence are additive API metadata. No frontend controls or layout were changed.

## Verification

Run `.venv/Scripts/python -m pytest services/api/tests -q` on Windows. The regression scenarios cover midnight and weekly rollover, GTFS service days, real gap lengths, closing-time encounters, missing/private/disconnected entrances, candidate selection, limits, evidence refresh and reuse, plus the existing journey and guardian flows.

Run `.venv/Scripts/python -X utf8 scripts/evaluate_routes.py` for four cached SF journeys. It checks score totals, gap geometry and default detour bounds without calling providers.

These checks verify implementation behavior. They do not establish field accuracy of the chosen weights. Missing business hours and unverified staffing cannot be manufactured from unavailable source data; the product continues to report those limits.
