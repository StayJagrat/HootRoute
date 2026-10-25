# Walking, cycling and wheelchair / step-free journeys

Work is on `Two_Categories`. The earlier `Final_Edit` corrections are carried forward as uncommitted changes because this branch was created from the earlier baseline. No branch has been committed or pushed for this feature.

## Options

The planner retains the existing design and adds a travel-mode selector before the request field. Preferences are stored on this device only.

- **Walking** retains the existing network, default pace of 1.35 m/s, score weights and options.
- **Cycling** defaults to an estimated 15 km/h. Users can choose 10, 15, 20 or 25 km/h, prefer mapped bike lanes, and avoid rough surfaces. Bicycle access restrictions, stairs, dismount-only paths, one-way streets, bicycle exceptions and roundabouts are applied to a directed graph. When requested, the recommendation prefers the candidate with more mapped bike-lane coverage within the existing detour limit. The seven-factor conditions score remains separate and unchanged.
- **Wheelchair / step-free** defaults to an estimated 3 km/h, avoids rough surfaces and uses a 5% maximum **mapped** incline. Users can choose 2, 3, 4 or 5 km/h, a 3%, 5% or 8% mapped-incline preference, and optionally require explicit wheelchair access tags. Mapped steps, wheelchair=no/limited, restricted foot access, recorded width below 0.9 m, recorded kerbs above 0.03 m or raised kerbs with no height, and poor recorded smoothness are excluded. These are routing preferences, not a building-code certification or a claim of suitability for every person or device.

Unknown wheelchair, surface, incline, sidewalk, kerb and entrance details remain unknown. Route results and the active journey show missing coverage. Requiring wheelchair tags can produce no connected route; the API returns a clear error rather than falling back to walking. No model invents access data.

The cached map often represents street centerlines rather than complete sidewalk/crossing geometry. Chosen places snap to the mapped network using the existing 250 m maximum; the strict wheelchair-tag option uses 50 m. Access between a chosen place and that network is unverified and is disclosed. A field check is still needed for unrecorded obstructions, entrance access, kerb ramps and slopes. Cycling turn-restriction relations and temporary conditions absent from the cached extract are not established by the available data.

## Complete flow

`travelMode: walk | cycle | wheelchair` and `travelOptions` pass through plans, conversational requests, approvals/re-scoring, reviewed-plan caching, walk creation, SQLite storage, restart recovery and obstacle re-planning. Guardian pages identify the travel mode. GPS replay, arrival-time hours, route inspection and remaining-time estimates use the selected pace.

Optional `travelOptions`: `speedKmh`, `preferCycleways`, `avoidRoughSurfaces`, `requireKnownAccess`, `maxInclinePct`. The API validates mode-specific pace ranges and rejects invalid input. Existing clients that omit the new fields remain walking clients.

Mode graphs and score references have distinct cache keys. Planning a ride or step-free journey never mutates the walking graph. The new controls use native selects and labeled checkboxes with keyboard access and the existing design tokens. No visual redesign, new fonts or new assets were introduced.

## Data definitions

- [OSM wheelchair tags](https://wiki.openstreetmap.org/wiki/Key:wheelchair)
- [Bicycle one-way exceptions](https://wiki.openstreetmap.org/wiki/Key:oneway:bicycle)
- [Mapped incline values](https://wiki.openstreetmap.org/wiki/Key:incline)
- [Kerb details](https://wiki.openstreetmap.org/wiki/Key:kerb)

Tests cover restrictions, one-way exceptions, pace-dependent timing, missing access data, option validation, cache separation, persistence, reviewed-plan handoff and mode-preserving live recovery. Live provider credentials are disabled during tests; paid checks still require approval in the product.

## Verification

- Full backend suite: 87 passed, 1 skipped (optional uAgents runtime).
- Final focused regression run after review: 57 passed, including both modes through plan, inspection, evidence, journey creation and live recovery.
- TypeScript and production Vite build passed.
- Browser verified cycling route selection and labelled GPS replay, wheelchair pace and route results, keyboard access to the new controls, and the strict-access error when no nearby mapped connection matches the selected options.

Both local repository copies are on `Two_Categories` with matching uncommitted source edits. `main` and `Final_Edit` retain their existing commits. The local preview uses a temporary database and disabled provider credentials.
