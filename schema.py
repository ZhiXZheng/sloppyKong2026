"""
FloodNet communication schemas.

This module defines the wire protocol shared by the simulation, rescue-team
agents, radio network, courier drone, and dashboard.

Design rules:
- Messages describe facts or proposals; receiving an event does not
  automatically authorise a world-state change.
- `observed_at` and `observer_id` belong to the original observation and must
  be preserved when a message is relayed.
- `created_at` records when the message was created; `picked_up_at` records
  transport history. Neither replaces the original observation timestamp.
- Delivery is at-least-once: consumers should deduplicate using `message_id`
  and make handlers idempotent.
- Version checks, claim arbitration, action validation, and world mutation
  are application logic, not responsibilities of these data models.
- For each entity compare (entity_revision, observed_tick, observer_id,
  observation_id.hex) lexicographically; larger wins. Revisions are assigned
  by the simulation and copied by observers. Never order by relay time.
- Resolve claims in (claimed_at_tick, team_id, claim_id.hex) order (smallest
  wins), after checking authoritative pickup state. Apply resolutions by
  resolution_version. UUIDs and timestamps must be injected deterministically
  by the seeded scheduler when reproducible serialized runs are required.
- Models are mutable data containers, not deep-immutable records. Transports
  must preserve the original envelope and observation contents when relaying.

Requires Pydantic >= 2.0.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


SCHEMA_VERSION = "2.0"


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class ProtocolModel(BaseModel):
    """Base class for all protocol objects."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )


# ---------------------------------------------------------------------------
# Shared identifiers and enumerations
# ---------------------------------------------------------------------------

class AgentRole(str, Enum):
    RESCUE_TEAM = "rescue_team"
    COURIER_DRONE = "courier_drone"
    SIMULATION = "simulation"
    DASHBOARD = "dashboard"


class MessageType(str, Enum):
    # Simulation/world information
    WORLD_SNAPSHOT = "world.snapshot"
    OBSERVATION = "world.observation"
    BELIEF_UPDATE = "world.belief_update"
    BELIEF_SNAPSHOT = "world.belief_snapshot"
    CIVILIAN_STATUS_UPDATE = "world.civilian_status_update"
    FLOOD_UPDATE = "world.flood_update"

    # Rescue task coordination
    TASK_CLAIM = "rescue.task_claim"
    TASK_CLAIM_RESOLUTION = "rescue.task_claim_resolution"
    ACTION_PROPOSAL = "rescue.action_proposal"
    ACTION_RESULT = "rescue.action_result"

    # Courier transport
    COURIER_PACKET = "courier.packet"
    COURIER_RECEIPT = "courier.receipt"

    # Network and operational messages
    HEARTBEAT = "network.heartbeat"
    LINK_STATUS = "network.link_status"
    AGENT_STATUS = "agent.status"
    SITUATION_BRIEF = "ai.situation_brief"
    AI_REQUEST = "ai.rescue_request"
    AI_RECOMMENDATION = "ai.rescue_recommendation"
    DRONE_STATUS = "courier.status"


class EntityType(str, Enum):
    CIVILIAN_GROUP = "civilian_group"
    SHELTER = "shelter"
    FLOOD_CELL = "flood_cell"
    RESCUE_TEAM = "rescue_team"


class CivilianStatus(str, Enum):
    """DELIVERED means safely at shelter. LOST means the group's cell flooded
    before pickup. Both are terminal."""
    UNKNOWN = "unknown"
    REPORTED = "reported"
    AVAILABLE = "available"
    CLAIMED = "claimed"
    PICKED_UP = "picked_up"
    DELIVERED = "delivered"
    LOST = "lost"


class ClaimStatus(str, Enum):
    PROVISIONAL = "provisional"
    CONFIRMED = "confirmed"
    RELEASED = "released"
    REJECTED = "rejected"
    COMPLETED = "completed"


class ActionType(str, Enum):
    MOVE = "move"
    PICKUP = "pickup"
    DROP_OFF = "drop_off"
    WAIT = "wait"


class ActionStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    COMPLETED = "completed"
    FAILED = "failed"


class LinkState(str, Enum):
    UP = "up"
    DOWN = "down"
    DEGRADED = "degraded"


class AgentState(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"


# ---------------------------------------------------------------------------
# Geometry and world entities
# ---------------------------------------------------------------------------

class GridPosition(ProtocolModel):
    x: int = Field(ge=0, le=19)
    y: int = Field(ge=0, le=19)


class EntityReference(ProtocolModel):
    entity_type: EntityType
    entity_id: str = Field(min_length=1)


class CivilianGroup(ProtocolModel):
    group_id: str = Field(min_length=1)
    position: GridPosition
    size: int = Field(ge=1)
    status: CivilianStatus = CivilianStatus.AVAILABLE
    picked_up_by_team_id: Optional[str] = Field(default=None, min_length=1)
    delivered_to_shelter_id: Optional[str] = Field(default=None, min_length=1)
    last_updated_at: AwareDatetime = Field(default_factory=utc_now)


class Shelter(ProtocolModel):
    """Capacity and occupants count people."""
    shelter_id: str = Field(min_length=1)
    position: GridPosition
    capacity: Optional[int] = Field(default=None, ge=0)
    occupants: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_capacity(self) -> "Shelter":
        if self.capacity is not None and self.occupants > self.capacity:
            raise ValueError("occupants exceed shelter capacity")
        return self


class RescueTeamState(ProtocolModel):
    """Capacity and carried_civilians count people, not groups."""
    team_id: str = Field(min_length=1)
    position: GridPosition
    capacity: int = Field(default=1, ge=1)
    carried_civilians: int = Field(default=0, ge=0)
    status: AgentState = AgentState.ONLINE
    neighbourhood_id: str = Field(min_length=1)
    carried_group_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_capacity(self) -> "RescueTeamState":
        if self.carried_civilians > self.capacity:
            raise ValueError("carried civilians exceed team capacity")
        if len(set(self.carried_group_ids)) != len(self.carried_group_ids):
            raise ValueError("carried_group_ids must be unique")
        if bool(self.carried_group_ids) != bool(self.carried_civilians):
            raise ValueError("carried civilians and group IDs must both be present or empty")
        if len(self.carried_group_ids) > self.carried_civilians:
            raise ValueError("each carried group must contain at least one person")
        return self


# ---------------------------------------------------------------------------
# Observation and local-belief protocols
# ---------------------------------------------------------------------------

class Observation(ProtocolModel):
    """
    A fact observed by one agent.

    `observed_at` and `observer_id` must remain unchanged when this object is
    copied into a belief update or courier packet.
    """

    observation_id: UUID = Field(default_factory=uuid4)
    observer_id: str = Field(min_length=1)
    entity: EntityReference
    position: Optional[GridPosition] = None
    observed_status: Optional[str] = None
    observed_at: AwareDatetime
    observed_tick: int = Field(ge=0)
    entity_revision: int = Field(ge=0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    details: dict[str, Any] = Field(default_factory=dict)


class BeliefUpdate(ProtocolModel):
    """A team-local belief derived from one or more original observations."""

    team_id: str = Field(min_length=1)
    entity: EntityReference
    position: Optional[GridPosition] = None
    believed_status: Optional[str] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_observation_ids: list[UUID] = Field(default_factory=list)
    # Timestamp of the newest source observation, not the time of forwarding.
    source_observed_at: AwareDatetime
    source_observed_tick: int = Field(ge=0)
    source_entity_revision: int = Field(ge=0)
    belief_version: int = Field(ge=1)
    updated_at: AwareDatetime = Field(default_factory=utc_now)


# ---------------------------------------------------------------------------
# Rescue claims, actions, and authoritative results
# ---------------------------------------------------------------------------

class TaskClaim(ProtocolModel):
    """
    A provisional or confirmed claim on a civilian group.

    Claims coordinate future work only. They must never undo a completed
    pickup or delivery.
    """

    claim_id: UUID = Field(default_factory=uuid4)
    team_id: str = Field(min_length=1)
    civilian_group_id: str = Field(min_length=1)
    status: ClaimStatus = ClaimStatus.PROVISIONAL
    claim_version: int = Field(default=1, ge=1)
    claimed_at_tick: int = Field(ge=0)
    claimed_at: AwareDatetime = Field(default_factory=utc_now)
    expires_at: Optional[AwareDatetime] = None
    reason: Optional[str] = None

    @model_validator(mode="after")
    def validate_expiry(self) -> "TaskClaim":
        if self.expires_at and self.expires_at <= self.claimed_at:
            raise ValueError("expires_at must be later than claimed_at")
        return self


class TaskClaimResolution(ProtocolModel):
    civilian_group_id: str = Field(min_length=1)
    winning_team_id: Optional[str] = None
    winning_claim_id: Optional[UUID] = None
    resolved_status: ClaimStatus
    conflicting_claim_ids: list[UUID] = Field(default_factory=list)
    resolution_reason: str = Field(min_length=1)
    resolved_at: AwareDatetime = Field(default_factory=utc_now)
    resolved_at_tick: int = Field(ge=0)
    resolution_version: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_winner(self) -> "TaskClaimResolution":
        if (self.winning_team_id is None) != (self.winning_claim_id is None):
            raise ValueError("winning team and claim must be supplied together")
        if self.winning_team_id == "":
            raise ValueError("winning_team_id must not be empty")
        if self.resolved_status == ClaimStatus.CONFIRMED and self.winning_claim_id is None:
            raise ValueError("confirmed resolution requires a winner")
        if self.resolved_status in (ClaimStatus.RELEASED, ClaimStatus.REJECTED) and self.winning_claim_id is not None:
            raise ValueError("released or rejected resolution cannot have a winner")
        return self


class ActionProposal(ProtocolModel):
    """An agent's requested action; the simulation validates it."""

    action_id: UUID = Field(default_factory=uuid4)
    team_id: str = Field(min_length=1)
    action_type: ActionType
    target_position: Optional[GridPosition] = None
    target_entity_id: Optional[str] = None
    based_on_world_tick: int = Field(ge=0)
    based_on_belief_version: int = Field(default=1, ge=1)
    explanation: Optional[str] = None
    proposed_at: AwareDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_action_target(self) -> "ActionProposal":
        if self.action_type == ActionType.MOVE and self.target_position is None:
            raise ValueError("MOVE actions require target_position")
        if self.action_type in (ActionType.PICKUP, ActionType.DROP_OFF):
            if not self.target_entity_id:
                raise ValueError(
                    f"{self.action_type.value} actions require target_entity_id"
                )
        return self


class ActionResult(ProtocolModel):
    """Deterministic simulation response to an action proposal."""

    action_id: UUID
    team_id: str
    status: ActionStatus
    applied_at_tick: int = Field(ge=0)
    resulting_position: Optional[GridPosition] = None
    affected_entity_id: Optional[str] = None
    message: Optional[str] = None


class CivilianStatusUpdate(ProtocolModel):
    civilian_group_id: str = Field(min_length=1)
    status: CivilianStatus
    changed_by_team_id: str = Field(min_length=1)
    world_tick: int = Field(ge=0)
    entity_revision: int = Field(ge=0)
    delivered_to_shelter_id: Optional[str] = Field(default=None, min_length=1)
    changed_at: AwareDatetime = Field(default_factory=utc_now)


# ---------------------------------------------------------------------------
# Network and courier-drone protocols
# ---------------------------------------------------------------------------

class NetworkLinkStatus(ProtocolModel):
    link_id: str = Field(min_length=1)
    neighbourhood_a: str = Field(min_length=1)
    neighbourhood_b: str = Field(min_length=1)
    state: LinkState
    changed_at: AwareDatetime = Field(default_factory=utc_now)


class Heartbeat(ProtocolModel):
    agent_id: str = Field(min_length=1)
    role: AgentRole
    state: AgentState
    current_world_tick: int = Field(ge=0)
    sent_at: AwareDatetime = Field(default_factory=utc_now)


class FloodUpdate(ProtocolModel):
    """Complete set of flooded cells at this revision, not a delta."""

    world_tick: int = Field(ge=0)
    revision: int = Field(ge=0)
    flood_cells: list[GridPosition] = Field(default_factory=list)


class AgentStatus(ProtocolModel):
    agent_id: str = Field(min_length=1)
    neighbourhood_id: str = Field(min_length=1)
    state: AgentState
    world_tick: int = Field(ge=0)
    radio_connected: bool
    ai_enabled: bool = True
    current_target_id: Optional[str] = None
    decision_context_version: int = Field(ge=1)

    @property
    def ai_available(self) -> bool:
        return self.radio_connected and self.ai_enabled and self.state != AgentState.OFFLINE


class AreaInformationFreshness(ProtocolModel):
    """Freshness known locally to the drone; None means never received."""

    neighbourhood_id: str = Field(min_length=1)
    latest_observed_tick: Optional[int] = Field(default=None, ge=0)


class DroneState(ProtocolModel):
    drone_id: str = Field(min_length=1)
    position: GridPosition
    enabled: bool = True
    destination_neighbourhood: Optional[str] = None
    carried_packet_ids: list[UUID] = Field(default_factory=list)
    area_freshness: list[AreaInformationFreshness] = Field(default_factory=list)
    world_tick: int = Field(ge=0)


class TeamBeliefSnapshot(ProtocolModel):
    """Only locally known information; never populated from global truth."""

    team_id: str = Field(min_length=1)
    belief_version: int = Field(ge=1)
    world_tick: int = Field(ge=0)
    observations: list[Observation] = Field(default_factory=list)
    claims: list[TaskClaim] = Field(default_factory=list)


class AIRescueRequest(ProtocolModel):
    """Bump context on target, task or connectivity changes; enforce timeout in code."""

    request_id: UUID = Field(default_factory=uuid4)
    seed: int
    beliefs: TeamBeliefSnapshot
    decision_context_version: int = Field(ge=1)
    current_target_id: Optional[str] = None
    requested_at: AwareDatetime = Field(default_factory=utc_now)
    timeout_seconds: float = Field(default=3.0, gt=0, le=3.0)


class RelayedMessage(ProtocolModel):
    """
    A message carried by the drone.

    The original envelope is retained intact. Relay metadata is additive and
    must not alter the observation timestamps inside its payload.
    """

    envelope: "MessageEnvelope"
    picked_up_at: AwareDatetime = Field(default_factory=utc_now)
    original_sender_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_sender(self) -> "RelayedMessage":
        if self.original_sender_id != self.envelope.sender_id:
            raise ValueError("original_sender_id must match the original envelope")
        return self


class CourierPacket(ProtocolModel):
    packet_id: UUID = Field(default_factory=uuid4)
    drone_id: str = Field(min_length=1)
    source_neighbourhood: str = Field(min_length=1)
    destination_neighbourhood: str = Field(min_length=1)
    messages: list[RelayedMessage] = Field(default_factory=list)
    departed_at: AwareDatetime = Field(default_factory=utc_now)
    delivered_at: Optional[AwareDatetime] = None

    @model_validator(mode="after")
    def validate_delivery_time(self) -> "CourierPacket":
        if self.delivered_at and self.delivered_at < self.departed_at:
            raise ValueError("delivered_at cannot precede departed_at")
        return self


class CourierReceipt(ProtocolModel):
    packet_id: UUID
    drone_id: str = Field(min_length=1)
    receiving_neighbourhood: str = Field(min_length=1)
    received_message_ids: list[UUID] = Field(default_factory=list)
    duplicate_message_ids: list[UUID] = Field(default_factory=list)
    received_at: AwareDatetime = Field(default_factory=utc_now)


# ---------------------------------------------------------------------------
# World snapshots and AI assistance
# ---------------------------------------------------------------------------

class WorldSnapshot(ProtocolModel):
    """A snapshot for initialisation or dashboard display, not shared truth."""

    world_tick: int = Field(ge=0)
    created_at: AwareDatetime = Field(default_factory=utc_now)
    civilian_groups: list[CivilianGroup] = Field(default_factory=list)
    shelters: list[Shelter] = Field(default_factory=list)
    rescue_teams: list[RescueTeamState] = Field(default_factory=list)
    flood_cells: list[GridPosition] = Field(default_factory=list)
    drone: Optional[DroneState] = None
    agent_statuses: list[AgentStatus] = Field(default_factory=list)


class AIRescueRecommendation(ProtocolModel):
    """
    Untrusted AI suggestion.

    The simulation must independently validate the selected target/action.
    """

    team_id: str = Field(min_length=1)
    request_id: UUID
    decision_context_version: int = Field(ge=1)
    recommended_target_id: Optional[str] = None
    recommended_action: ActionType
    explanation: str = ""
    missing_information: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    based_on_belief_version: int = Field(ge=1)
    generated_at: AwareDatetime = Field(default_factory=utc_now)


class SituationBrief(ProtocolModel):
    """Human-readable operational summary; never authoritative world state."""

    generated_for_tick: int = Field(ge=0)
    summary: str = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)
    stale_information: list[str] = Field(default_factory=list)
    unknown_information: list[str] = Field(default_factory=list)
    generated_at: AwareDatetime = Field(default_factory=utc_now)


# ---------------------------------------------------------------------------
# Common transport envelope
# ---------------------------------------------------------------------------

class MessageEnvelope(ProtocolModel):
    """
    Standard wrapper for every message sent over radio or courier.

    `message_id` is the idempotency/deduplication key.
    `event_id` identifies the logical event; it may be shared by copies sent
    to multiple recipients.
    `sequence_number` is monotonic per sender when the sender can guarantee it.
    """

    schema_version: str = SCHEMA_VERSION
    message_id: UUID = Field(default_factory=uuid4)
    event_id: UUID = Field(default_factory=uuid4)
    message_type: MessageType
    sender_id: str = Field(min_length=1)
    sender_role: AgentRole
    recipient_id: Optional[str] = None
    neighbourhood_id: Optional[str] = None
    sequence_number: Optional[int] = Field(default=None, ge=0)
    correlation_id: Optional[UUID] = None
    causation_id: Optional[UUID] = None
    created_at: AwareDatetime = Field(default_factory=utc_now)
    world_tick: Optional[int] = Field(default=None, ge=0)
    payload: dict[str, Any]

    @model_validator(mode="after")
    def validate_payload(self) -> "MessageEnvelope":
        # Nested courier envelopes take this same path recursively.
        parse_payload(self)
        return self

    @field_validator("schema_version")
    @classmethod
    def supported_schema_version(cls, value: str) -> str:
        if value != SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported schema_version {value!r}; expected {SCHEMA_VERSION!r}"
            )
        return value


# ---------------------------------------------------------------------------
# Payload registry and helpers
# ---------------------------------------------------------------------------

PAYLOAD_MODELS: dict[MessageType, type[BaseModel]] = {
    MessageType.WORLD_SNAPSHOT: WorldSnapshot,
    MessageType.OBSERVATION: Observation,
    MessageType.BELIEF_UPDATE: BeliefUpdate,
    MessageType.BELIEF_SNAPSHOT: TeamBeliefSnapshot,
    MessageType.FLOOD_UPDATE: FloodUpdate,
    MessageType.AGENT_STATUS: AgentStatus,
    MessageType.DRONE_STATUS: DroneState,
    MessageType.AI_REQUEST: AIRescueRequest,
    MessageType.AI_RECOMMENDATION: AIRescueRecommendation,
    MessageType.CIVILIAN_STATUS_UPDATE: CivilianStatusUpdate,
    MessageType.TASK_CLAIM: TaskClaim,
    MessageType.TASK_CLAIM_RESOLUTION: TaskClaimResolution,
    MessageType.ACTION_PROPOSAL: ActionProposal,
    MessageType.ACTION_RESULT: ActionResult,
    MessageType.COURIER_PACKET: CourierPacket,
    MessageType.COURIER_RECEIPT: CourierReceipt,
    MessageType.HEARTBEAT: Heartbeat,
    MessageType.LINK_STATUS: NetworkLinkStatus,
    MessageType.SITUATION_BRIEF: SituationBrief,
}


def make_message(
    *,
    message_type: MessageType,
    sender_id: str,
    sender_role: AgentRole,
    payload: ProtocolModel,
    recipient_id: Optional[str] = None,
    neighbourhood_id: Optional[str] = None,
    sequence_number: Optional[int] = None,
    correlation_id: Optional[UUID] = None,
    causation_id: Optional[UUID] = None,
    world_tick: Optional[int] = None,
) -> MessageEnvelope:
    """Create a standard envelope from a typed payload."""
    message_type = MessageType(message_type)
    expected_model = PAYLOAD_MODELS.get(message_type)
    if expected_model is None:
        raise ValueError(f"No payload model registered for {message_type.value}")
    if not isinstance(payload, expected_model):
        raise TypeError(
            f"{message_type.value} expects {expected_model.__name__}, "
            f"not {type(payload).__name__}"
        )

    return MessageEnvelope(
        message_type=message_type,
        sender_id=sender_id,
        sender_role=sender_role,
        recipient_id=recipient_id,
        neighbourhood_id=neighbourhood_id,
        sequence_number=sequence_number,
        correlation_id=correlation_id,
        causation_id=causation_id,
        world_tick=world_tick,
        payload=payload.model_dump(mode="json"),
    )


def parse_payload(envelope: MessageEnvelope) -> BaseModel:
    """Validate and parse an envelope payload into its registered model."""
    model = PAYLOAD_MODELS.get(envelope.message_type)
    if model is None:
        raise ValueError(
            f"No payload model registered for {envelope.message_type.value}"
        )
    return model.model_validate(envelope.payload)


def serialize_message(envelope: MessageEnvelope) -> str:
    """Serialize an envelope for transport or persistence."""
    parse_payload(envelope)
    return envelope.model_dump_json()


def deserialize_message(raw: str) -> MessageEnvelope:
    """Deserialize and validate a transport message."""
    return MessageEnvelope.model_validate_json(raw)


__all__ = [
    "FloodUpdate",
    "AgentStatus",
    "AreaInformationFreshness",
    "DroneState",
    "TeamBeliefSnapshot",
    "AIRescueRequest",
    "SCHEMA_VERSION",
    "AgentRole",
    "MessageType",
    "EntityType",
    "CivilianStatus",
    "ClaimStatus",
    "ActionType",
    "ActionStatus",
    "LinkState",
    "AgentState",
    "GridPosition",
    "EntityReference",
    "CivilianGroup",
    "Shelter",
    "RescueTeamState",
    "Observation",
    "BeliefUpdate",
    "TaskClaim",
    "TaskClaimResolution",
    "ActionProposal",
    "ActionResult",
    "CivilianStatusUpdate",
    "NetworkLinkStatus",
    "Heartbeat",
    "RelayedMessage",
    "CourierPacket",
    "CourierReceipt",
    "WorldSnapshot",
    "AIRescueRecommendation",
    "SituationBrief",
    "MessageEnvelope",
    "PAYLOAD_MODELS",
    "make_message",
    "parse_payload",
    "serialize_message",
    "deserialize_message",
]
