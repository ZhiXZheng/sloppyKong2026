# Person B: AI and rescue-team agents

All Person B implementation, tests, examples and handoff notes live here. Shared
interfaces remain in root `schema.py` (protocol 2.0). The source plan remains at
[`docs/PERSON_B_IMPLEMENTATION_PLAN.md`](../docs/PERSON_B_IMPLEMENTATION_PLAN.md).

## Run from the repository root

```powershell
python -m pip install -r requirements.txt
python -m person_b.check
python -m person_b.demo
python -m person_b.demo --visual
```

Use `.venv\Scripts\python.exe` instead of `python` if using the project environment.
Only Pydantic is required. The Claude adapter uses Python's standard HTTP client;
rules-only execution needs no token, network or Claude SDK.

`--visual` opens a standalone animated grid replay in your default browser. It shows
both rescue teams, civilian groups, pickup loads, the shelter and a courier flight
matching the fixture's tick-9 delivery. Play/pause, step, scrub, change speed and
switch between drone ON/OFF. The default crop follows the activity area; choose
Full 20 x 20 to see the whole grid. This is a global world view, including civilian
groups teams have not discovered. The fixture contains no flood cells.

The courier route is scripted in this offline fixture; Person C's production drone
still needs integrating. Team positions and civilian states come from actual demo
frames. Playback makes no Claude calls and needs no internet or server.

Use `--visual --no-open` to generate `person_b/output/grid-demo.html` without opening
a browser. The generated page can also be opened directly, and can be shared as a
single file. It contains scenario data only, with no API key or other credentials.

The demo prints readable headings and event lines per tick as the run progresses,
with team names, positions, action reasons, results and final score banners.
Add `--json` for the full JSON records, suitable for saving or processing.
Each tick labels
the scenario, tick and drone setting and includes both teams' observations,
claims/messages, action explanations, results, position/load changes and rescue
score. Final summaries follow each run. Use `python -m person_b.demo --summary-only`
to hide tick records, or `--ticks 10` to shorten each comparison run. The separate
border-conflict fixture also prints its two ticks. Programmatic callers can pass
`on_tick=callback` to stream records; `run_comparison()` returns them in `tick_events`.

The deterministic fixture produces 3/3 people delivered with the courier and 2/3
without it, over the same 30 ticks. A separate border fixture gives one winning
target after reconnect. These are small A/C stand-ins, not the production world,
radio transport or drone movement implementation. `run_comparison()` also returns
all action proposals so tests can check reproducibility and repeated pickups.

## Completed stages

| Plan stage | Implementation |
|---|---|
| Local beliefs and basic decisions | `beliefs.py`: provenance, revision ordering, duplicate handling, snapshots/updates. `policy.py`: capacity/ownership checks, BFS, stable targets, shelter return. |
| Claims, controller and AI | `controller.py`: tick API, provisional claims, action/result correlation, event triggers. `ai_client.py`: trusted request metadata, structured Claude output, bounded workers and three-second deadlines. |
| Disconnection/conflicts | Immediate AI invalidation, rule fallback, newer-resolution application, claim tombstones/expiry, carried-group delivery unaffected by losing future work. |
| Cache, switch and integration | `ai_cache.py`: canonical local prompts, seed-specific SQLite cache, bounded entries. Shared `AISettings`, dashboard view, drone ON/OFF fixture and optional background `briefing.py`. |
| Tests and demo | `tests/`, `check.py`, `demo.py`, and explicit single-request `smoke_claude.py`. |

## Integration API

```python
from person_b import AISettings, RescueController

settings = AISettings(enabled=False)  # shared by every team
controller = RescueController("team-1", seed=42, settings=settings)

# Called by A/C's deterministic scheduler, on its own thread:
controller.receive(delivered_envelopes)         # C's original wire envelopes
controller.observe(local_observations)         # A has already applied visibility
controller.apply_result(previous_action_result)  # when there is a result
decision = controller.step(own_state, connectivity, world_tick)

# A validates/applies decision.action; C routes decision.outbound.
# D reads decision.ui, a detached dictionary of dashboard state.
```

`own_state` is this team's `RescueTeamState`. `connectivity` is either a boolean
meaning AI reachability or this team's `AgentStatus`. It does not mean merely
that local radios work. Call `step` in fixed team order. The optional
`monotonic_now` argument must use the same clock as `AIService.clock`; simulation
ticks are not wall-clock seconds. Omit it in the live application.

Each step returns exactly one `ActionProposal`. While a previous action awaits a
terminal result, it returns WAIT and still polls AI deadlines. ACCEPTED is not
completion. A must return COMPLETED/REJECTED/FAILED and provide updated own state;
B never changes authoritative positions, loads, civilian status or score.

`decision.outbound` contains shared `MessageEnvelope` objects for new local
observations and claim transitions. Only local observations whose `observer_id`
matches the controller are published; received observations are not rebroadcast.
C chooses radio recipients, stores/forwards original envelopes and delivers claim
resolutions. `receive` handles a `CourierPacket` by processing its original inner
envelopes, respecting their recipients and original IDs.

`decision.ui` includes serialized `AgentStatus`, explicit `ai_available`,
`ai_pending`, `ai_status`, reason, local belief snapshot and per-entity age in ticks.
Use `controller.beliefs.updates(tick, controller.runtime.timestamp)` if D needs
typed `BeliefUpdate` objects. These views are detached from controller memory.

## Local observation conventions and rules

- Civilian observations need position, an `available` status and integer
  `details["size"]` before selection. A claimed civilian requires an active own
  claim. Unknown sizes/statuses, other-team claims and terminal groups are excluded.
- Optional civilian detail keys: `picked_up_by_team_id`, `delivered_to_shelter_id`.
  Authoritative `CivilianStatusUpdate` messages preserve previously known static
  location/size and replace status using their world revision/tick.
- Shelter observations need a position. `capacity=None` means unlimited;
  finite capacity requires integer `occupants`. Loads count people, whole groups
  are picked up, and carried people return to a known shelter before new work.
- Flood observations use `EntityType.FLOOD_CELL`, position and
  `details["traversable"]`. Anything except explicit True blocks that known cell.
- Movement is four-neighbour BFS with fixed neighbour order. Unknown cells are
  tentatively traversable by default; set `unknown_traversable=False` for a
  conservative map. A validates each adjacent step and supplies corrected local
  observations after rejection. Generic errors do not invent obstacle facts.
- No eligible target means WAIT. Autonomous exploration is intentionally omitted;
  seed enough local sightings/reports for the demo, or add exploration with A.
- Never feed global snapshots or full `FloodUpdate` maps into team beliefs. C/A
  must filter delivery/visibility. Full-world messages are ignored by the controller.
- Claims remain provisional until A's arbiter emits a resolution. Arbitration
  orders `(claimed_at_tick, team_id, claim_id.hex)` ascending after checking real
  pickup state. B consumes monotonically newer resolution versions. A completed
  pickup is never undone. No auctions or distributed consensus are implemented.
- Claim expiry uses injected simulation timestamps. Terminal claims and
  resolutions are kept as tombstones for the duration of a run.

## Enable Claude

Put `API_KEY=...` in the repository `.env` (already ignored by Git), or set
`ANTHROPIC_API_KEY` in the environment. Credentials are read only by the adapter
and are not included in prompts, caches, UI events or error output.

```python
from person_b.ai_client import AIService, ClaudeProvider
from person_b.ai_cache import DecisionCache

provider = ClaudeProvider(max_requests=100, max_tokens=256)
cache = DecisionCache()  # optional path for a persistent SQLite cache
service = AIService(provider, cache=cache, max_workers=2)
settings = AISettings(enabled=True)
controller = RescueController("team-1", seed=42, ai_service=service, settings=settings)
# Share settings and service across all teams.

# Later, even during a run:
settings.enabled = False  # blocks live calls and cached AI decisions on next step

# At application shutdown (outside the tick loop):
service.close(wait=True)
cache.close()
```

Model defaults to `claude-haiku-4-5-20251001`; override with
`FLOODNET_CLAUDE_MODEL` or the provider's `model` argument. Prompts contain only
local observations/claims, own state and eligible IDs. The model selects a target;
Python validates it and derives the actual action and movement.

One request is allowed per team and at most two provider jobs run across the shared
service by default. A timed-out job retains its worker slot until it finishes;
cancellation cannot forcibly stop an HTTP call. There is no automatic retry.
Timeout/error falls back to rules; another meaningful event is needed to request
again. Late, disconnected or stale-context responses are ignored. A global switch
change cannot undo an already submitted network call, but its result is discarded.

The cache stores model content only and reattaches current request metadata on
each hit. Cache identity includes seed, canonical local state, model, generation
settings and prompt version. Requests are gated before both cache and live access.
Default limits are 100 network attempts per provider instance, 256 output tokens
per request and 24,000 prompt characters. These are usage bounds, not a dollar
meter. `provider.calls` and `provider.usage` expose acknowledged consumption.

An explicit live check makes one paid request with no retries:

```powershell
python -m person_b.smoke_claude --live
# Only for diagnosing first-use network/schema latency, outside the simulation:
python -m person_b.smoke_claude --live --timeout 20
```

Verified during implementation: Haiku 4.5 selected the eligible target in 2.515 s,
with 595 input and 163 output tokens. Earlier connection/timeout attempts returned
no usage data. This does not guarantee future responses meet the deadline; the
three-second controller fallback remains necessary.

The adapter follows Anthropic's [Messages API](https://platform.claude.com/docs/en/api/http/messages)
and [structured output format](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).
Automated tests use fake providers and never make paid calls.

## Optional summaries and remaining team integration

`BriefingService.submit(snapshot, runtime.timestamp, ai_available=...)` builds a
team-local briefing in a separate bounded worker. With a Claude provider it can
generate a short summary; otherwise it uses a deterministic operational summary.
Call `poll()` without blocking. Original observation ages and unknown-data warnings
remain attached; summaries never enter team beliefs. Gate submission with the
current AI settings/connectivity and discard a briefing if the UI context changed.
Call `close()` on shutdown. Global command briefings and n8n belong to separate
dashboard/network integration.

Before merging the team application, A/C must connect filtered sensing, transport,
claim arbitration and action results; D must consume the dashboard view. No
production A/C/D modules exist in this checkout, so their integration is exercised
through the offline stand-ins. Keep the same seed, horizon and AI-off setting for
the real drone comparison, then measure actual delivered people.
