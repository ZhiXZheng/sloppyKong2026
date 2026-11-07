# Person B implementation plan: AI and rescue-team agents

Based on `docs/FLOODNET_PLAN.md` and protocol 2.0 in `schema.py`.

## Outcome

Deliver rescue-team controllers that act from their own knowledge, continue with
deterministic rules during communication failures, and accept validated,
event-triggered AI recommendations when connected. A drone-delivered observation
must be able to change a team's next decision without exposing global world state.

Build the complete rules-only rescue loop before adding live AI. Target a working
two-team, three-group fixture first; scale through configuration during integration.

## Ownership and integration agreements (first 20 minutes)

| Partner | Agree inputs and outputs | Ownership boundary |
|---|---|---|
| A: Simulation | Own `RescueTeamState`, filtered local `Observation` objects, action results, known shelter information; output one `ActionProposal` per team per tick | A owns sensing visibility, legal movement, authoritative pickup/drop-off, entity revisions and scoring. B owns local belief merging, route planning and action selection. |
| C: Network | Delivered original `MessageEnvelope` objects and per-team `AgentStatus.radio_connected`; output claim/observation envelopes | C owns transport, duplicate delivery, drone routing and connectivity computation. B deduplicates received information and invalidates pending AI on connectivity changes. |
| A + C: Claims | B emits `TaskClaim`; a designated arbiter emits `TaskClaimResolution` | Agree that A owns authoritative arbitration, with C delivering claims/resolutions. B applies resolutions and releases losing future tasks. Never let agents arbitrate using hidden global data. |
| D: Dashboard | Read-only `TeamBeliefSnapshot`, `BeliefUpdate`, `AgentStatus`, action explanations and optional `SituationBrief` | D owns presentation. B supplies reasons, pending/fallback state and information ages. |

Use existing schema classes for shared data; keep controller bookkeeping internal.
Confirm these remaining conventions before integration:

- Observation `details`: civilian `size`, pickup owner and shelter destination;
  shelter capacity/occupancy; flood traversability. Missing data stays unknown.
- Shelter position can be common initial knowledge; civilian positions cannot.
- Four-neighbour movement, flood restrictions, whole-group pickup, team capacity,
  and what to do when no known group fits. Default: whole groups only.
- MOVE means one adjacent cell; DROP_OFF targets a shelter ID. A validates both.
- `ActionResult.COMPLETED` means the action took effect. ACCEPTED alone does not
  justify marking a group picked up or delivered.
- Connectivity means AI reachability, not merely contact with another local team.
- `FloodUpdate` is a complete flood set: do not feed the global update into team
  knowledge. A must provide local flood observations or an explicitly scoped view.
- Explanations can use `ActionProposal.explanation`; any richer UI-only event
  record is a local adapter, not a new wire message type without agreement.

The original plan mentions timestamp ordering; protocol 2.0 specifies revision/tick
ordering. Follow `schema.py` and use original timestamps for age display.

## Proposed files

| File | Responsibility |
|---|---|
| `agents/beliefs.py` | Per-team observations, claims, deduplication, versions and snapshots |
| `agents/policy.py` | Eligibility checks, deterministic target selection and local path planning |
| `agents/controller.py` | Tick orchestration, targets, claims, action results and AI triggers |
| `agents/ai_client.py` | Provider interface, Claude adapter, parsing, pending requests and deadlines |
| `agents/ai_cache.py` | Canonical prompt construction and cached model content |
| `agents/briefing.py` | Optional operational summary generation |
| `tests/test_agents.py` | Belief, policy, claims and controller tests |
| `tests/test_ai.py` | Fake-provider timeout, invalid output, caching and stale-reply tests |
| `examples/person_b_demo.py` | Small offline integration fixture with synthetic observations/results |

Add package initialisers as needed. Keep provider imports optional so rules-only
execution and tests work without credentials or the Claude SDK.

## 1. Local beliefs and deterministic policy (0:20–1:15)

1. Implement `BeliefStore` per team, keyed by `(entity_type, entity_id)`.
   Retain original observations and source provenance; copy mutable schema data
   at ownership boundaries so a dashboard or transport cannot mutate team memory.
2. Deduplicate envelopes by `message_id` and observations by `observation_id`.
   Merge per entity using the schema's lexicographic key:
   `(entity_revision, observed_tick, observer_id, observation_id.hex)`; larger wins.
   Increment `belief_version` only when effective knowledge changes.
3. Store claims by claim ID/version and resolutions by group/resolution version.
   Keep losing/released/completed states so late claims cannot resurrect work.
4. Export `TeamBeliefSnapshot` and `BeliefUpdate` using original source timestamps
   and revisions. Snapshots contain only accepted local knowledge.
5. Implement eligibility: known civilian, known location/size, fits available
   capacity, no known active claim by another team, and not picked up/delivered/
   rescued. Unknown status or ownership must not be treated as confirmed availability.
6. Select the nearest eligible group deterministically. Prefer known route length
   with group ID as a tie-break. Use BFS over locally known traversability, with a
   fixed neighbour order; agree whether unknown cells are tentatively traversable.
   If tentative movement is rejected, update only from feedback actually received.
7. Preserve a valid current target to avoid oscillation. Carrying people takes
   priority: travel to a known shelter and drop off before selecting new work.
   With no eligible target, use WAIT for MVP; add deterministic exploration only
   if the scenario requires it to discover the initial groups.

**Checkpoint:** two controllers with different observations choose independently;
both can complete a rules-only pickup/drop-off cycle through a fake A interface.

## 2. Claims, controller and AI requests (1:15–2:15)

Proposed local API, to be agreed with A/C:

```python
controller.receive(envelopes)                 # delivered messages only
controller.observe(local_observations)        # visibility-filtered by A
controller.apply_result(action_result)        # correlate by action_id
decision = controller.step(own_state, connectivity, world_tick, monotonic_now)
# decision: one ActionProposal, outbound envelopes and read-only UI state
```

The scheduler calls controllers in fixed team-ID order after message delivery and
local sensing. Inject simulation time/ID factories for reproducible fixtures; use
an injected monotonic clock for real-time AI deadlines.

1. Claim a selected group once, not once per step. Disconnected claims are
   provisional; connected claims become confirmed only through the agreed arbiter.
   Release on abandonment; complete only after authoritative pickup feedback.
2. Produce MOVE, PICKUP, DROP_OFF or WAIT proposals with current tick and belief
   version. The controller never modifies world entities or score.
3. Define AI triggers: newly known civilian, lost claim, reconnection, task
   completion. Coalesce triggers and allow at most one outstanding request per team.
4. Construct `AIRescueRequest` from local knowledge and target context. Include own
   position, capacity, load and known shelter information in the canonical prompt
   through explicit local inputs; the request schema does not contain own state.
5. Use a fake provider first. Then add Claude structured JSON through a configurable
   Haiku-class model. Verify the current provider API when implementing the adapter;
   keep its model name/configuration outside policy code.
6. Ask the model for target, explanation and missing information. Parse with
   Pydantic; attach trusted team/request/context/version metadata in Python rather
   than relying on the model to echo it correctly. Python derives movement steps.
   For MVP accept civilian-target recommendations only; defer other AI actions.
7. Submit work outside the tick loop through a bounded background worker/executor.
   Poll completed work at tick boundaries. Keep a valid current target while waiting;
   use rules immediately if there is no valid target. Never call `future.result()`
   on unfinished work from the simulation thread.
8. Enforce the three-second deadline using monotonic time and provider timeouts.
   Expire requests without blocking; invalidate late results even if cancellation
   cannot stop the underlying call. Bound workers and prevent retries every tick.

**Checkpoint:** simulated slow or malformed AI never stalls movement or crashes a tick.

## 3. Disconnection and conflict handling (2:15–3:15)

- On loss of AI reachability, disable submissions immediately, invalidate pending
  requests and bump `decision_context_version`. Continue with the rule policy;
  retain the existing target only if that policy still considers it eligible.
- Gate cached recommendations by the same connectivity/global AI switch as live AI.
- On target/task/connectivity change, bump context. Accept replies only if team,
  request, context and belief version still match, the deadline has not elapsed,
  AI remains available, and the target is still locally eligible. Otherwise fall back.
- Treat drone observations exactly like radio observations. Duplicate delivery
  changes nothing; genuinely newer knowledge updates beliefs and can invalidate
  a target or trigger a new decision. A drone delivery does not restore AI access.
- Apply only newer claim resolutions. If this team loses future work, release its
  target, invalidate AI and choose again. Already carried civilians still go to a
  shelter; claim reconciliation cannot undo a successful pickup.
- Use schema claim order `(claimed_at_tick, team_id, claim_id.hex)`, smallest first,
  in the arbiter integration fixture. A checks pickup state before arbitration.
- Correlate action results and apply each once. A rejected pickup must not create
  local carried civilians. Use returned observations to correct beliefs; avoid
  inventing facts from a generic rejection message.

**Checkpoint:** isolated teams claim the border group; reconnection changes the
loser's future task, while A permits only one physical pickup.

## 4. Cache, AI switch and integration (3:15–4:00)

1. Build a stable canonical prompt: sorted entities/claims, explicit prompt version,
   own local state, and relevant observation ages. Exclude random request IDs and
   wall-clock transport timestamps. Key cache by `(seed, canonical_prompt)`; include
   model identity and generation settings in that canonical input.
2. Cache model decision content, not a complete recommendation with old request
   metadata. Reattach current request metadata and validate eligibility on every hit.
3. Provide one global AI-off configuration and per-team status. Rules-only mode
   must make zero provider calls and finish the fixture from start to finish.
4. Supply D with belief snapshots, current target, AI pending/rules reason and
   action explanations. `ai_available` is a Python property, so export it explicitly
   in a UI view if needed; it is not included automatically in schema JSON.
5. Integrate A/C's seeded drone ON/OFF runs. Keep AI off or use fixed cached
   decisions for the comparison so network delivery is the tested difference.
   Measure rescued people; do not hard-code the example scores from the main plan.
6. If time remains, add `SituationBrief` on demand from a clearly scoped snapshot.
   Label global dashboard briefings separately from team-local knowledge. Summaries
   never enter the belief store as facts. Optional n8n remains C's integration.

## 5. Failure tests and demo preparation (4:00–5:00)

Use fake providers and clocks; no live API is required for automated tests.

| Case | Required result |
|---|---|
| Same observation through radio and drone | One effective update; no extra belief version or AI trigger |
| Stale/equal-revision out-of-order observation | Schema ordering wins; transport time has no effect |
| Different teams receive different observations | Each selects from its own knowledge; hidden groups never enter prompts |
| Unknown, terminal, oversized or other-team-claimed AI target | Reject; deterministic fallback |
| AI malformed JSON, error, or reply after three seconds | No crash or blocked tick; continue target/rules |
| Reply after belief, target, task or connectivity change | Discard, including disconnect/reconnect during one request |
| AI disabled or team isolated | Zero live calls and zero cached AI decisions |
| Many triggers while a request is pending | Bounded work; no per-tick request storm |
| Duplicate/stale claim resolution or action result | No rollback or repeated state transition |
| Losing claim after a successful pickup | Continue delivery; no second pickup |
| Cached decision under a new request | Fresh metadata; same validation as a live reply |
| Same seeded fixture with fixed AI responses | Same actions, claims and rescue outcome |

Finish with the shared three-minute demo: connected recommendation, disconnect
and rule fallback, drone update changing a decision, reconnect and border conflict,
then measured ON/OFF results. Reserve this final hour for fixes and rehearsal.

## Definition of done and scope cuts

- Each team owns a separate belief store and acts through shared schema proposals.
- Rules-only rescue works throughout a radio failure; AI is optional and nonblocking.
- Original provenance survives relays; stale/duplicate information is harmless.
- Conflicts change future work without reversing physical rescue events.
- D can display local knowledge, target, decision reason and connectivity state.
- Focused tests and a runnable offline Person B fixture demonstrate these behaviours.

If behind schedule, cut briefings, n8n, model-controlled actions beyond target
selection, advanced allocation and optional exploration. Preserve beliefs, rules,
claims, timeout/fallback behaviour and the drone-driven change of decision.
