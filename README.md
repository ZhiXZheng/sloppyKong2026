# sloppyKong2026
GreatUniHack2026

## Shared protocol

Install dependencies with `python -m pip install -r requirements.txt`.
Run schema checks with `python -m unittest discover -s tests -v`.

`schema.py` defines protocol **2.0**. Version 1.0 envelopes are rejected;
producers must migrate together:

- Observations require `observed_tick` and simulation-assigned `entity_revision`.
  Belief updates require the corresponding source tick/revision and `belief_version`.
- Claims require `claimed_at_tick`; resolutions require `resolved_at_tick` and
  a monotonically increasing `resolution_version` per civilian group.
- Team states require `neighbourhood_id`. Capacity and carried counts are people;
  nonempty loads also require unique `carried_group_ids`. The simulation checks
  their sizes against the authoritative groups.
- AI recommendations echo `request_id`, `decision_context_version`, and
  `based_on_belief_version` from the request. Bump the context when the target,
  task, or connectivity changes; discard mismatched or timed-out replies.
- All timestamps require a timezone. Enums remain enum objects in Python and
  serialize as strings in JSON. Use `model_dump(mode="json")` for wire payloads.

Every message type has a payload model. Envelope construction and deserialization
validate payloads, including nested courier messages. Preserve original message
IDs and observation provenance when forwarding. The module documents deterministic
observation and claim ordering; seeded runs must also supply deterministic IDs and
timestamps if byte-for-byte reproducibility is needed.

`TeamBeliefSnapshot` contains only locally known observations and claims.
`AgentStatus.ai_available` combines radio connectivity, the AI switch, and agent
state. `DroneState.area_freshness` records ticks known to the drone; `None` means
never received and should be visited before known areas (tie-break by area ID).

`DELIVERED` and legacy `RESCUED` both mean safely at shelter. Score each group
once, using its size. Pickup ownership and destination are recorded on
`CivilianGroup`; the simulation must enforce lifecycle transitions, prevent
duplicate pickup, and reconcile loaded groups with team state.

Deduplication, stale-update rejection, claim arbitration, three-second AI timeout,
AI availability checks before dispatch, target validation, and world mutation
remain application responsibilities. Schema validation supplies their contracts;
it does not execute the simulation.


## Dashboard with Claude courier drone

Install Python and frontend dependencies, then run these in separate terminals:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn floodnet.server:app --host 127.0.0.1 --port 8000
```

```powershell
npm ci
npm run dev
```

Open http://localhost:3000. Vite proxies `/api` to the Python server. Keep a
single backend worker because simulation state lives in memory.

Set `API_KEY=your-anthropic-key` in the repository `.env`, or set `API_KEY` /
`ANTHROPIC_API_KEY` in the server environment. Keys are read only by Python;
never use a `VITE_` prefix for credentials. The existing dashboard design is unchanged.

The drone uses `claude-haiku-5-5`, the lowest-priced current Claude model in
[Anthropic's model comparison](https://platform.claude.com/docs/en/models/overview)
(checked November 7, 2026). Override it with the server environment variable
`FLOODNET_CLAUDE_MODEL` if needed. The frontend components and layout are unchanged.

### Multi-agent drone system

`floodnet/sim/drone_agents.py` contains three cooperating agents:

- **Scout:** Claude prioritises upcoming search destinations while a continuous
  coverage route visits unobserved sensor footprints. Slow or failed replies never
  stop flight. Completion means all grid cells were actually scanned, including
  edges. Civilian discoveries come only from real drone/team observations.
- **Rescue planner:** Claude ranks observed civilian groups to maximise people saved,
  accounting for size, capacity, reported flood proximity, and estimated dry routes.
  This is evidence-based prioritisation, not a guarantee of a globally optimal rescue.
- **Courier:** Physically approaches teams to deliver evidence and orders during a
  radio outage. It follows last reported positions and sensor sightings, searching
  nearby if a stale position is empty. It cannot read hidden live team positions.

A deterministic coordinator reserves each task for one team and issues one flight
command. Both teams busy means the rescue remains queued. The first eligible team
reported free takes the next task; if multiple teams are free, the closest eligible
team by a dry ground route takes it. Capacity and shelter-route feasibility are
checked before dispatch. A team stays busy through pickup and delivery to shelter.
Online idle teams await orders rather than independently claiming the same civilians.
Offline idle teams instead take one random cardinal step on locally observed dry
ground each tick. Each team has its own seeded random stream, independent of world
IDs and online decisions. Teams still prioritise flood escape, delivered rescue
orders, and transporting passengers to shelter; they wait if all adjacent cells
are blocked. Undelivered reservations do not stop wandering or reveal an order.
Only physical contact transfers an offline team's reports and queued instructions.
Claude priorities are retained for unchanged evidence when new civilians appear.
For a new discovery, the coordinator gives planning one tick to respond; if it is
still unavailable, it dispatches eligible queued work under the standing availability
policy. Already queued rescues go to a newly free team immediately. These interim
orders are explicitly marked as rule fallback with zero AI confidence, and can gain
an AI explanation when an unchanged target receives a validated response. Orders
and team ownership are never redirected merely because a late AI reply arrives.

With radio connected, evidence and orders are transmitted immediately. During an
outage, knowledge and orders transfer only within one cell (Chebyshev distance) of
an actual team. A pending courier order does not move that team. Availability is
only known from radio reports or physical contacts; remote completions are not
magically revealed. Busy-team rendezvous are scheduled around estimated completion
times. Nonurgent status checks wait for the current scouting leg to finish, so
repeated visits to busy or unreachable teams cannot starve map coverage. New orders
still take courier priority. Rising water can interrupt any
route; local teams replan on observed flood information and can escape a flooded
position only to adjacent dry ground. The world validates all actions.

Normal playback runs **one tick every 20 seconds**. The existing 2x and 4x controls
use 10-second and 5-second ticks. Manual `/api/step` requests remain immediate.

Scout and planner requests run off the simulation thread, with at most one request
per role and two workers. Each has a 12-second deadline and a 512 output-token cap;
only generated tokens are billed. Search choices are prefetched during flight and
only meaningful evidence changes trigger rescue replanning. The shared provider
limits requests to 100 per server lifetime, including resets.

Transient failures retry on a later simulation tick using exponential backoff
(2, 4, 8, 16, then 30 seconds), respecting a larger API `Retry-After` interval.
Authentication, invalid model/request, account spend caps, and the local request
budget stop automatic retries instead of generating repeated failures. The provider
makes one HTTP attempt per scheduled request. Local validation still rejects unknown
IDs, duplicates, changed targets, and expired replies. New discoveries do not count
as API failures or invalidate useful recommendations for unchanged groups.

Press Play (or Launch Drone) to run. The existing event feed shows discoveries,
priorities, reservations, order deliveries, coverage completion and service status.
Team panels show the actual plan and distinguish standing-policy fallback from
Claude reasoning. `/api/state` includes `drone.agentSystem.scout/planner.diagnostics`
with request/success/failure counters, error categories, response latency, retry
delay, deadline and disabled state. `drone.agentSystem.api` exposes the shared
request budget and token usage; `queuedTasks` shows waiting rescues. Scanned-cell
counts and decision sources are explicit. Credentials and raw API errors are never
exposed. Missing keys are reported and do not start a hidden AI-labelled patrol.
Pause stops the drone; existing team orders continue. Return overrides missions
and lands at the scenario launch position.

Reset clears all agent evidence, orders, and missions; stale worker replies cannot
modify the new world. The standalone `python -m floodnet.sim` CLI remains the
separate deterministic rule-agent demo.

Run verification without API charges:

```powershell
python -m pytest tests person_b/tests -q
node tests/test_paths.cjs
npm run build
```


### Source guide and comments

Maintained source is documented with module overviews, public-contract notes, and
purpose comments for controllers, validation, transport, and simulation transitions.
Python purpose comments deliberately leave executable ASTs and Pydantic class
docstrings unchanged, preserving both runtime behaviour and model JSON schemas.
Generated `dist/`, exported replay output, and installed dependencies are artifacts,
not source to maintain by hand.

- `floodnet/server.py` owns dashboard API state, locking, and frontend adaptation.
- `floodnet/sim/drone_agents.py` owns scout/planner/courier cooperation and task ownership.
- `floodnet/sim/world.py` validates movement and authoritative civilian lifecycles.
- `floodnet/sim/pathing.py` and `scenario.py` define geometry and deterministic flood inputs.
- `schema.py` defines validated protocol contracts and observation provenance.
- `person_b/` holds reusable local-belief, transport, caching, controller, and replay code.
- `src/store/` and `src/simulation/pythonClient.ts` connect existing operator controls to Python.
- `src/components/` presents snapshots; corridor circles, labels, the fixed beam, and
  the obsolete Radio Zones toggle are removed. Radio controls and network status remain.
- `src/simulation/` retains the separate browser-only fallback demo.
- `tests/` and `person_b/tests/` cover safety, connectivity, handoffs, provider errors,
  offline wandering, protocol validation, and replay consistency without paid API calls.
