"""
FloodNet communication schemas.

This module defines the wire protocol shared by the simulation, rescue-team
agents, radio network, courier drone, and dashboard.

Design rules:
- Messages are immutable facts or proposals; receiving an event does not
  automatically authorise a world-state change.
- `observed_at` and `observer_id` belong to the original observation and must
  be preserved when a message is relayed.
- `created_at` records when the message was created; `relayed_at` records
  transport history. Neither replaces the original observation timestamp.
- Delivery is at-least-once: consumers should deduplicate using `message_id`
  and make handlers idempotent.
- Version checks, claim arbitration, action validation, and world mutation
  are application logic, not responsibilities of these data models.

Requires Pydantic >= 2.0.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SCHEMA_VERSION = "1.0"


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class ProtocolModel(BaseModel):
    """Base class for all protocol objects."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        use_enum_values=True,
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


class EntityType(str, Enum):
    CIVILIAN_GROUP = "civilian_group"
    SHELTER = "shelter"
    FLOOD_CELL = "flood_cell"
    RESCUE_TEAM = "rescue_team"


class CivilianStatus(str, Enum):
    UNKNOWN = "unknown"
    REPORTED = "reported"
    AVAILABLE = "available"
    CLAIMED = "claimed"
    PICKED_UP = "picked_up"
    DELIVERED = "delivered"
    RESCUED = "rescued"


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
    last_updated_at: datetime = Field(default_factory=utc_now)


class Shelter(ProtocolModel):
    shelter_id: str = Field(min_length=1)
    position: GridPosition
    capacity: Optional[int] = Field(default=None, ge=0)
    occupants: int = Field(default=0, ge=0)


class RescueTeamState(ProtocolModel):
    team_id: str = Field(min_length=1)
    position: GridPosition
    capacity: int = Field(default=1, ge=1)
    carried_civilians: int = Field(default=0, ge=0)
    status: AgentState = AgentState.ONLINE


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
    observed_at: datetime
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
    source_observed_at: datetime
    updated_at: datetime = Field(default_factory=utc_now)


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
    claimed_at: datetime = Field(default_factory=utc_now)
    expires_at: Optional[datetime] = None
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
    resolved_at: datetime = Field(default_factory=utc_now)


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
    proposed_at: datetime = Field(default_factory=utc_now)

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
    changed_at: datetime = Field(default_factory=utc_now)


# ---------------------------------------------------------------------------
# Network and courier-drone protocols
# ---------------------------------------------------------------------------

class NetworkLinkStatus(ProtocolModel):
    link_id: str = Field(min_length=1)
    neighbourhood_a: str = Field(min_length=1)
    neighbourhood_b: str = Field(min_length=1)
    state: LinkState
    changed_at: datetime = Field(default_factory=utc_now)


class Heartbeat(ProtocolModel):
    agent_id: str = Field(min_length=1)
    role: AgentRole
    state: AgentState
    current_world_tick: int = Field(ge=0)
    sent_at: datetime = Field(default_factory=utc_now)


class RelayedMessage(ProtocolModel):
    """
    A message carried by the drone.

    The original envelope is retained intact. Relay metadata is additive and
    must not alter the observation timestamps inside its payload.
    """

    envelope: "MessageEnvelope"
    picked_up_at: datetime = Field(default_factory=utc_now)
    original_sender_id: str = Field(min_length=1)


class CourierPacket(ProtocolModel):
    packet_id: UUID = Field(default_factory=uuid4)
    drone_id: str = Field(min_length=1)
    source_neighbourhood: str = Field(min_length=1)
    destination_neighbourhood: str = Field(min_length=1)
    messages: list[RelayedMessage] = Field(default_factory=list)
    departed_at: datetime = Field(default_factory=utc_now)
    delivered_at: Optional[datetime] = None

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
    received_at: datetime = Field(default_factory=utc_now)


# ---------------------------------------------------------------------------
# World snapshots and AI assistance
# ---------------------------------------------------------------------------

class WorldSnapshot(ProtocolModel):
    """A snapshot for initialisation or dashboard display, not shared truth."""

    world_tick: int = Field(ge=0)
    created_at: datetime = Field(default_factory=utc_now)
    civilian_groups: list[CivilianGroup] = Field(default_factory=list)
    shelters: list[Shelter] = Field(default_factory=list)
    rescue_teams: list[RescueTeamState] = Field(default_factory=list)
    flood_cells: list[GridPosition] = Field(default_factory=list)


class AIRescueRecommendation(ProtocolModel):
    """
    Untrusted AI suggestion.

    The simulation must independently validate the selected target/action.
    """

    team_id: str = Field(min_length=1)
    recommended_target_id: Optional[str] = None
    recommended_action: ActionType
    explanation: str = ""
    missing_information: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    based_on_belief_version: int = Field(ge=1)
    generated_at: datetime = Field(default_factory=utc_now)


class SituationBrief(ProtocolModel):
    """Human-readable operational summary; never authoritative world state."""

    generated_for_tick: int = Field(ge=0)
    summary: str = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)
    stale_information: list[str] = Field(default_factory=list)
    unknown_information: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utc_now)


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
    created_at: datetime = Field(default_factory=utc_now)
    world_tick: Optional[int] = Field(default=None, ge=0)
    payload: dict[str, Any]

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
    expected_model = PAYLOAD_MODELS.get(message_type)
    if expected_model is not None and not isinstance(payload, expected_model):
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
    return envelope.model_dump_json()


def deserialize_message(raw: str) -> MessageEnvelope:
    """Deserialize and validate a transport message."""
    return MessageEnvelope.model_validate_json(raw)


__all__ = [
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
