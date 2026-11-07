"""Tick-driven rescue controller. World mutation belongs to Person A."""

import time
from dataclasses import dataclass

from schema import (
    ActionProposal, ActionResult, ActionStatus, ActionType, AgentRole, AgentState,
    AgentStatus, AIRescueRequest, CivilianStatus, CivilianStatusUpdate, ClaimStatus, CourierPacket,
    EntityReference, EntityType, MessageEnvelope, MessageType, Observation,
    TaskClaim, TaskClaimResolution, parse_payload,
)
from .ai_cache import canonical_prompt
from .beliefs import BeliefStore
from .policy import candidates, select_target, shelter_route
from .runtime import Runtime


@dataclass
class AISettings:
    """Share across controllers; changing enabled gates live and cached decisions."""
    enabled: bool = True


@dataclass
class Decision:
    action: ActionProposal
    outbound: list[MessageEnvelope]
    ui: dict


class RescueController:
    def __init__(self, team_id, seed=0, ai_service=None, settings=None,
                 runtime=None, unknown_traversable=True):
        self.team_id = team_id
        self.seed = seed
        self.beliefs = BeliefStore(team_id)
        self.ai = ai_service
        self.settings = settings if settings is not None else AISettings()
        self.runtime = runtime or Runtime(f"floodnet/{seed}/{team_id}")
        self.unknown_traversable = unknown_traversable
        self.target = None
        self.context_version = 1
        self.reason = "Rules: no known target"
        self._connected = None
        self._availability = None
        self._ready_recommendation = None
        self._load = None
        self._trigger = False
        self._outbound = []
        self._local_observations = []
        self._outstanding = None
        self._terminal_results = set()
        self._completed_groups = set()
        self._tick = 0
        self._area = None

    def observe(self, observations):
        """Accept A's local sensing; publish this team's new observations to C."""
        self._observe(observations, publish=True)

    def _observe(self, observations, publish=False):
        for observation in observations:
            known = self.beliefs.get(observation.entity.entity_type, observation.entity.entity_id)
            changed = self.beliefs.observe(observation)
            if changed and publish and observation.observer_id == self.team_id:
                self._local_observations.append(observation.model_copy(deep=True))
            if changed and known is None and observation.entity.entity_type == EntityType.CIVILIAN_GROUP:
                self._trigger = True

    def receive(self, envelopes):
        for envelope in envelopes:
            if envelope.recipient_id not in (None, self.team_id):
                continue
            payload = parse_payload(envelope)
            if not self.beliefs.accept_message(envelope.message_id):
                continue
            if isinstance(payload, CourierPacket):
                self.receive([item.envelope for item in payload.messages])
            elif isinstance(payload, Observation):
                self._observe([payload])
            elif isinstance(payload, TaskClaim):
                self.beliefs.merge_claim(payload)
            elif isinstance(payload, TaskClaimResolution):
                if self.beliefs.resolve(payload) and payload.civilian_group_id == self.target:
                    if payload.winning_team_id != self.team_id or payload.resolved_status != ClaimStatus.CONFIRMED:
                        self._trigger = True
            elif isinstance(payload, ActionResult):
                self.apply_result(payload)
            elif isinstance(payload, CivilianStatusUpdate):
                known = self.beliefs.get(EntityType.CIVILIAN_GROUP, payload.civilian_group_id)
                details = dict(known.details) if known else {}
                if payload.status in (CivilianStatus.PICKED_UP, CivilianStatus.DELIVERED, CivilianStatus.RESCUED):
                    details["picked_up_by_team_id"] = payload.changed_by_team_id
                details["delivered_to_shelter_id"] = payload.delivered_to_shelter_id
                self._observe([Observation(observation_id=envelope.event_id,
                    observer_id=envelope.sender_id,
                    entity=EntityReference(entity_type=EntityType.CIVILIAN_GROUP,
                                           entity_id=payload.civilian_group_id),
                    observed_status=payload.status.value, observed_at=payload.changed_at,
                    observed_tick=payload.world_tick, entity_revision=payload.entity_revision,
                    position=known.position if known else None, details=details)])
            # WORLD_SNAPSHOT/FLOOD_UPDATE are intentionally not global team knowledge.

    def _invalidate(self, reason):
        self.context_version += 1
        self._ready_recommendation = None
        if self.ai:
            self.ai.invalidate(self.team_id, reason)

    def _emit(self, message_type, payload):
        self._outbound.append(MessageEnvelope(message_type=message_type,
            message_id=self.runtime.new_id("message"), event_id=self.runtime.new_id("event"),
            sender_id=self.team_id, sender_role=AgentRole.RESCUE_TEAM,
            neighbourhood_id=self._area, world_tick=self._tick,
            created_at=self.runtime.timestamp(self._tick), payload=payload.model_dump(mode="json")))

    def _finish_claim(self, group_id, status):
        claim = self.beliefs.own_active_claim(group_id)
        if claim:
            updated = claim.model_copy(update={"status": status, "claim_version": claim.claim_version + 1})
            if self.beliefs.merge_claim(updated):
                self._emit(MessageType.TASK_CLAIM, updated)

    def _set_target(self, target):
        if target == self.target:
            return
        if self.target:
            self._finish_claim(self.target, ClaimStatus.RELEASED)
        self.target = target
        self._invalidate("Target changed")

    def apply_result(self, result):
        if result.team_id != self.team_id or result.action_id in self._terminal_results:
            return
        proposal = self._outstanding
        if proposal is None or proposal.action_id != result.action_id:
            return
        if result.status == ActionStatus.ACCEPTED:
            return
        self._terminal_results.add(result.action_id)
        self._outstanding = None
        self._tick = result.applied_at_tick
        if result.status == ActionStatus.COMPLETED:
            if proposal.action_type == ActionType.PICKUP:
                self._completed_groups.add(proposal.target_entity_id)
                self._finish_claim(proposal.target_entity_id, ClaimStatus.COMPLETED)
                self._set_target(None)
                self._trigger = True
            elif proposal.action_type == ActionType.DROP_OFF:
                self._invalidate("Delivery completed")
                self._trigger = True
        else:
            self.reason = "Rules: action rejected; awaiting local information"
            self._invalidate("Action rejected")
            self._trigger = True
        # A supplies the next own_state; generic errors never invent map facts.

    def step(self, own_state, connectivity, world_tick, monotonic_now=None):
        if own_state.team_id != self.team_id:
            raise ValueError("Controller received another team's state")
        if isinstance(connectivity, AgentStatus) and connectivity.agent_id != self.team_id:
            raise ValueError("Controller received another team's connectivity")
        now = time.monotonic() if monotonic_now is None else monotonic_now
        self._tick, self._area = world_tick, own_state.neighbourhood_id
        for observation in self._local_observations:
            self._emit(MessageType.OBSERVATION, observation)
        self._local_observations = []
        connected = connectivity.radio_connected if isinstance(connectivity, AgentStatus) else bool(connectivity)
        enabled = self.settings.enabled and (connectivity.ai_enabled if isinstance(connectivity, AgentStatus) else True)
        available = connected and enabled and own_state.status != AgentState.OFFLINE
        if isinstance(connectivity, AgentStatus):
            available = available and connectivity.state != AgentState.OFFLINE
        if connected != self._connected or available != self._availability:
            if self._connected is False and connected:
                self._trigger = True
            self._invalidate("Connectivity or AI switch changed")
        self._connected, self._availability = connected, available
        load = tuple(sorted(own_state.carried_group_ids))
        if self._load is not None and load != self._load:
            self._invalidate("Load changed")
        self._load = load
        self.beliefs.expire(self.runtime.timestamp(world_tick))
        if self.ai:
            reply = self.ai.poll(self.team_id, self.context_version,
                self.beliefs.version, available, now, self.runtime.timestamp(world_tick))
            if reply is not None:
                self._ready_recommendation = reply
        if self._ready_recommendation:
            ready = self._ready_recommendation
            if (not available or ready.decision_context_version != self.context_version or
                    ready.based_on_belief_version != self.beliefs.version):
                self._ready_recommendation = None

        status = AgentStatus(agent_id=self.team_id, neighbourhood_id=self._area,
            state=own_state.status, world_tick=world_tick, radio_connected=connected,
            ai_enabled=enabled, current_target_id=self.target,
            decision_context_version=self.context_version)
        action_type, position, entity_id = ActionType.WAIT, None, None
        if own_state.status == AgentState.OFFLINE:
            self.reason = "Offline: waiting"
        elif self._outstanding:
            self.reason = "Waiting for authoritative action result"
        elif own_state.carried_civilians:
            self._set_target(None)
            destination = shelter_route(self.beliefs, own_state, self.unknown_traversable)
            self.reason = "Rules: return carried civilians to shelter"
            if destination:
                _, entity_id, path = destination
                if path:
                    action_type, position = ActionType.MOVE, path[0]
                else:
                    action_type = ActionType.DROP_OFF
            else:
                self.reason = "Rules: no known reachable shelter with room"
        else:
            choices = candidates(self.beliefs, own_state, self._completed_groups, self.unknown_traversable)
            if self.target and self.target not in choices:
                self._set_target(None)
                self._trigger = True
            self._set_target(select_target(choices, self.target))
            self.reason = "Rules: nearest known available target" if self.target else "Rules: no known available target"

            # Claim before submitting AI, so the request includes our own claim version.
            if self.target and not self.beliefs.own_active_claim(self.target):
                claim = TaskClaim(claim_id=self.runtime.new_id("claim"), team_id=self.team_id,
                    civilian_group_id=self.target, status=ClaimStatus.PROVISIONAL,
                    claimed_at_tick=world_tick, claimed_at=self.runtime.timestamp(world_tick),
                    reason="Locally selected; awaiting arbitration" if connected else "Isolated provisional claim")
                if self.beliefs.merge_claim(claim):
                    self._emit(MessageType.TASK_CLAIM, claim)

            recommendation, self._ready_recommendation = self._ready_recommendation, None
            if recommendation:
                if recommendation.recommended_target_id in choices:
                    self._set_target(recommendation.recommended_target_id)
                    self.reason = f"AI: {recommendation.explanation}"
                    if not self.beliefs.own_active_claim(self.target):
                        claim = TaskClaim(claim_id=self.runtime.new_id("claim"), team_id=self.team_id,
                            civilian_group_id=self.target, claimed_at_tick=world_tick,
                            claimed_at=self.runtime.timestamp(world_tick), reason=self.reason)
                        if self.beliefs.merge_claim(claim):
                            self._emit(MessageType.TASK_CLAIM, claim)
                else:
                    self.reason = "Rules: AI target rejected by local validation"
            if self.ai and available and self._trigger and choices:
                request = AIRescueRequest(request_id=self.runtime.new_id("ai-request"), seed=self.seed,
                    beliefs=self.beliefs.snapshot(world_tick), current_target_id=self.target,
                    decision_context_version=self.context_version, requested_at=self.runtime.timestamp(world_tick))
                prompt = canonical_prompt(request, own_state, choices, self.ai.provider.model,
                                          self.ai.provider.max_tokens)
                if self.ai.submit(request, prompt, now):
                    self._trigger = False
            if self.target:
                _, path = choices[self.target]
                entity_id = self.target
                if path:
                    action_type, position = ActionType.MOVE, path[0]
                else:
                    action_type = ActionType.PICKUP
            if not connected:
                self.reason = "Isolated; " + self.reason
            elif not enabled:
                self.reason = "AI off; " + self.reason

        action = ActionProposal(action_id=self.runtime.new_id("action"), team_id=self.team_id,
            action_type=action_type, target_position=position, target_entity_id=entity_id,
            based_on_world_tick=world_tick, based_on_belief_version=self.beliefs.version,
            proposed_at=self.runtime.timestamp(world_tick), explanation=self.reason)
        if action_type != ActionType.WAIT:
            self._outstanding = action.model_copy(deep=True)
        status = status.model_copy(update={"current_target_id": self.target,
                                          "decision_context_version": self.context_version})
        snapshot = self.beliefs.snapshot(world_tick)
        ui = dict(status=status.model_dump(mode="json"), ai_available=available,
            ai_pending=bool(self.ai and self.team_id in self.ai.pending),
            ai_status=self.ai.last_reason.get(self.team_id, "Rules only") if self.ai else "Rules only",
            reason=self.reason, beliefs=snapshot.model_dump(mode="json"),
            information_age_ticks={f"{o.entity.entity_type.value}:{o.entity.entity_id}":
                                   max(0, world_tick - o.observed_tick) for o in snapshot.observations})
        outbound, self._outbound = self._outbound, []
        return Decision(action=action, outbound=outbound, ui=ui)
