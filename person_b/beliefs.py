"""Knowledge received by one team, without access to authoritative world state."""

from schema import (
    BeliefUpdate, ClaimStatus, TeamBeliefSnapshot,
)

ACTIVE = {ClaimStatus.PROVISIONAL, ClaimStatus.CONFIRMED}
TERMINAL = {ClaimStatus.RELEASED, ClaimStatus.REJECTED, ClaimStatus.COMPLETED}


# Compare authoritative source revision before tick and stable provenance tie-breakers.
def observation_order(observation):
    return (observation.entity_revision, observation.observed_tick,
            observation.observer_id, observation.observation_id.hex)


# Apply deterministic ordering when several local claims concern the same task.
def claim_order(claim):
    return claim.claimed_at_tick, claim.team_id, claim.claim_id.hex


# Hold one team's deduplicated observations, claims, and resolution tombstones.
class BeliefStore:
    # Start an isolated versioned store with independent message and observation deduplication.
    def __init__(self, team_id):
        self.team_id = team_id
        self.version = 1
        self._observations = {}
        self._claims = {}
        self._resolutions = {}
        self._seen_observations = set()
        self._seen_messages = set()

    # Accept each envelope identity once even if a courier delivers it repeatedly.
    def accept_message(self, message_id):
        if message_id in self._seen_messages:
            return False
        self._seen_messages.add(message_id)
        return True

    # Reject stale provenance and copy accepted observations so callers cannot mutate stored
    # facts.
    def observe(self, observation):
        if observation.observation_id in self._seen_observations:
            return False
        self._seen_observations.add(observation.observation_id)
        key = (observation.entity.entity_type, observation.entity.entity_id)
        old = self._observations.get(key)
        if old and observation_order(observation) <= observation_order(old):
            return False
        self._observations[key] = observation.model_copy(deep=True)
        self.version += 1
        return True

    # Return a defensive copy of the latest fact for a particular entity.
    def get(self, entity_type, entity_id):
        item = self._observations.get((entity_type, entity_id))
        return item.model_copy(deep=True) if item else None

    # Return stable, copied observations, optionally restricted to one entity type.
    def observations(self, entity_type=None):
        return [o.model_copy(deep=True) for key, o in sorted(self._observations.items())
                if entity_type is None or key[0] == entity_type]

    # Respect claim versions and terminal resolution tombstones when delayed claims arrive.
    def merge_claim(self, claim):
        old = self._claims.get(claim.claim_id)
        if old and (claim.claim_version <= old.claim_version or old.status in TERMINAL):
            return False
        resolution = self._resolutions.get(claim.civilian_group_id)
        if resolution and (resolution.resolved_status == ClaimStatus.COMPLETED or
                           claim.claimed_at_tick <= resolution.resolved_at_tick):
            # Late packets cannot resurrect claims already arbitrated.
            if claim.claim_id != resolution.winning_claim_id:
                return False
            if claim.status in ACTIVE:
                claim = claim.model_copy(update={"status": resolution.resolved_status})
        self._claims[claim.claim_id] = claim.model_copy(deep=True)
        self.version += 1
        return True

    # Apply only newer arbitration and reject losing active claims without resurrecting terminal
    # work.
    def resolve(self, resolution):
        old = self._resolutions.get(resolution.civilian_group_id)
        if old and (resolution.resolution_version <= old.resolution_version or
                    old.resolved_status == ClaimStatus.COMPLETED):
            return False
        self._resolutions[resolution.civilian_group_id] = resolution.model_copy(deep=True)
        for claim_id, claim in list(self._claims.items()):
            if claim.civilian_group_id != resolution.civilian_group_id:
                continue
            if claim.status in TERMINAL:
                continue
            if claim_id == resolution.winning_claim_id:
                status = resolution.resolved_status
            elif claim.claimed_at_tick <= resolution.resolved_at_tick or claim_id in resolution.conflicting_claim_ids:
                status = ClaimStatus.REJECTED
            else:
                continue
            self._claims[claim_id] = claim.model_copy(update={"status": status}, deep=True)
        self.version += 1
        return True

    # Expose copied claims in deterministic arbitration order.
    def claims(self):
        return [c.model_copy(deep=True) for c in sorted(self._claims.values(), key=claim_order)]

    def expire(self, timestamp):
        """Local expiry tombstones; never emit another team's claim transitions."""
        for claim_id, claim in list(self._claims.items()):
            if claim.status in ACTIVE and claim.expires_at is not None and claim.expires_at <= timestamp:
                self._claims[claim_id] = claim.model_copy(update={"status": ClaimStatus.RELEASED})
                self.version += 1

    # Find this team's current reservation for a group, if one exists.
    def own_active_claim(self, group_id):
        return next((c for c in self.claims() if c.team_id == self.team_id
                     and c.civilian_group_id == group_id and c.status in ACTIVE), None)

    # Prevent local planning from duplicating another known winner or completed rescue.
    def claimed_by_other(self, group_id):
        resolution = self._resolutions.get(group_id)
        if resolution:
            if resolution.resolved_status == ClaimStatus.COMPLETED:
                return True
            if resolution.resolved_status == ClaimStatus.CONFIRMED and resolution.winning_team_id != self.team_id:
                winner = self._claims.get(resolution.winning_claim_id)
                if winner is None or winner.status in ACTIVE:
                    return True
        return any(c.civilian_group_id == group_id and c.team_id != self.team_id
                   and c.status in ACTIVE for c in self._claims.values()) or any(
                       c.civilian_group_id == group_id and c.status == ClaimStatus.COMPLETED
                       for c in self._claims.values())

    # Package copied local knowledge and its version for AI or protocol consumers.
    def snapshot(self, tick):
        return TeamBeliefSnapshot(team_id=self.team_id, belief_version=self.version,
                                  world_tick=tick, observations=self.observations(), claims=self.claims())

    # Preserve observation provenance while translating local facts into belief-update messages.
    def updates(self, tick, timestamp):
        return [BeliefUpdate(team_id=self.team_id, entity=o.entity, position=o.position,
                believed_status=o.observed_status, confidence=o.confidence,
                source_observation_ids=[o.observation_id], source_observed_at=o.observed_at,
                source_observed_tick=o.observed_tick, source_entity_revision=o.entity_revision,
                belief_version=self.version, updated_at=timestamp(tick)) for o in self.observations()]
