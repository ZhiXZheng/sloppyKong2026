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
