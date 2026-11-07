"""Shared data contracts between simulation, agents, network and dashboard."""

from __future__ import annotations

from enum import Enum
from typing import Literal, Union

from pydantic import BaseModel, Field

Pos = tuple[int, int]


class CivilianStatus(str, Enum):
    WAITING = "waiting"
    PICKED_UP = "picked_up"
    RESCUED = "rescued"
    LOST = "lost"


class CivilianGroup(BaseModel):
    id: str
    pos: Pos
    size: int
    status: CivilianStatus = CivilianStatus.WAITING
    carried_by: str | None = None
    resolved_tick: int | None = None


class Team(BaseModel):
    id: str
    pos: Pos
    home_area: str
    sense_radius: int = 2
    speed: int = 1
    carrying: str | None = None


class Drone(BaseModel):
    id: str
    pos: Pos
    sense_radius: int = 3
    speed: int = 2


class Shelter(BaseModel):
    id: str
    pos: Pos
    occupants: int = 0


class Move(BaseModel):
    kind: Literal["move"] = "move"
    agent_id: str
    to: Pos


class Pickup(BaseModel):
    kind: Literal["pickup"] = "pickup"
    agent_id: str
    group_id: str


class Dropoff(BaseModel):
    kind: Literal["dropoff"] = "dropoff"
    agent_id: str


class Wait(BaseModel):
    kind: Literal["wait"] = "wait"
    agent_id: str


Action = Union[Move, Pickup, Dropoff, Wait]


class SeenCivilian(BaseModel):
    id: str
    pos: Pos
    size: int
    status: CivilianStatus


class SeenAgent(BaseModel):
    id: str
    pos: Pos
    kind: Literal["team", "drone"]


class Observation(BaseModel):
    """What one agent can sense this tick. Agents must not read World directly."""

    tick: int
    agent_id: str
    pos: Pos
    area: str
    carrying: str | None = None
    cells: list[tuple[int, int, bool]] = Field(default_factory=list)  # (x, y, flooded)
    civilians: list[SeenCivilian] = Field(default_factory=list)
    agents: list[SeenAgent] = Field(default_factory=list)
    shelter: Pos | None = None


class Event(BaseModel):
    tick: int
    kind: str  # moved | picked_up | rescued | lost | flooded | rejected
    agent_id: str | None = None
    group_id: str | None = None
    detail: str = ""


class Score(BaseModel):
    groups_total: int
    groups_rescued: int
    groups_lost: int
    people_total: int
    people_rescued: int
    people_lost: int
