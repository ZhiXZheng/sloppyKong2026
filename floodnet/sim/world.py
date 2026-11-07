"""Ground-truth world: grid, flood, movement, pickup, drop-off and scoring.

Speaks the shared protocol in schema.py:
- Agents learn about the world only through `observe()` -> list[schema.Observation]
  (plus their own `team_state()` / `drone_state()`).
- Agents change the world only by submitting `schema.ActionProposal`s to `step()`.
  Every proposal is validated here and answered with a `schema.ActionResult`, so an
  invalid (e.g. AI) recommendation can never break the simulation rules.
- The simulation owns entity revisions; observations copy them (see schema.py docstring).
- UUIDs and timestamps are derived from the seed and tick, so runs are reproducible.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from floodnet.sim.pathing import Pos, chebyshev, gp, manhattan, tup
from floodnet.sim.scenario import ScenarioConfig, compute_flood_ticks
from schema import (
    ActionProposal,
    ActionResult,
    ActionStatus,
    ActionType,
    CivilianGroup,
    CivilianStatus,
    CivilianStatusUpdate,
    DroneState,
    EntityReference,
    EntityType,
    FloodUpdate,
    Observation,
    RescueTeamState,
    WorldSnapshot,
)

FLOODED = "flooded"
TERMINAL = (CivilianStatus.DELIVERED, CivilianStatus.LOST)
FLOOD_ACTOR = "simulation"  # changed_by_team_id when the flood (not a team) changes a group


@dataclass
class StepOutcome:
    results: list[ActionResult] = field(default_factory=list)
    status_updates: list[CivilianStatusUpdate] = field(default_factory=list)
    lost_group_ids: list[str] = field(default_factory=list)
    newly_flooded: list[Pos] = field(default_factory=list)


class World:
    def __init__(self, cfg: ScenarioConfig):
        self.cfg = cfg
        self.width = cfg.width
        self.height = cfg.height
        self.tick = 0
        self._rng = random.Random(cfg.seed)
        self.flood_ticks = compute_flood_ticks(cfg)
        self.flooded: set[Pos] = {p for p, t in self.flood_ticks.items() if t <= 0}
        self.shelter = cfg.shelter.model_copy(deep=True)
        self.teams: dict[str, RescueTeamState] = {
            t.team_id: t.model_copy(deep=True) for t in cfg.teams
        }
        self.drones: dict[str, DroneState] = {
            d.drone_id: d.model_copy(deep=True) for d in cfg.drones
        }
        self.civilians: dict[str, CivilianGroup] = {
            c.group_id: c.model_copy(update={"last_updated_at": self.now()}, deep=True)
            for c in cfg.civilians
        }
        self.revisions: dict[str, int] = {gid: 0 for gid in self.civilians}
        self.shelter_revision = 0
        self.log: list[StepOutcome] = []
        for c in self.civilians.values():
            if tup(c.position) in self.flooded:
                raise ValueError(f"civilian group {c.group_id} starts in water")
        for t in self.teams.values():
            if tup(t.position) in self.flooded:
                raise ValueError(f"team {t.team_id} starts in water")

    # ---------- deterministic ids/time ----------
    def now(self) -> datetime:
        return self.cfg.start_time + timedelta(seconds=self.tick * self.cfg.tick_seconds)

    def new_uuid(self) -> uuid.UUID:
        return uuid.UUID(int=self._rng.getrandbits(128), version=4)

    # ---------- queries ----------
    def in_bounds(self, pos: Pos) -> bool:
        return 0 <= pos[0] < self.width and 0 <= pos[1] < self.height

    def is_flooded(self, pos: Pos) -> bool:
        return pos in self.flooded

    def area_of(self, pos: Pos) -> str:
        """neighbourhood_id of a cell."""
        return "west" if pos[0] < self.cfg.area_split_x else "east"

    def agent_ids(self) -> list[str]:
        return sorted(self.teams) + sorted(self.drones)

    def agent_pos(self, agent_id: str) -> Pos:
        if agent_id in self.teams:
            return tup(self.teams[agent_id].position)
        return tup(self.drones[agent_id].position)

    def team_state(self, team_id: str) -> RescueTeamState:
        return self.teams[team_id].model_copy(deep=True)

    def drone_state(self, drone_id: str) -> DroneState:
        return self.drones[drone_id].model_copy(deep=True)

    def is_done(self) -> bool:
        if self.tick >= self.cfg.max_ticks:
            return True
        return all(c.status in TERMINAL for c in self.civilians.values())

    # ---------- sensing ----------
    def _observation(self, observer: str, etype: EntityType, eid: str, pos: Pos,
                     status: str | None, revision: int, details: dict[str, Any] | None = None
                     ) -> Observation:
        return Observation(
            observation_id=self.new_uuid(),
            observer_id=observer,
            entity=EntityReference(entity_type=etype, entity_id=eid),
            position=gp(pos),
            observed_status=status,
            observed_at=self.now(),
            observed_tick=self.tick,
            entity_revision=revision,
            details=details or {},
        )

    def observe(self, agent_id: str) -> list[Observation]:
        """Facts this agent can sense right now (within its sense radius)."""
        if agent_id in self.teams:
            radius = self.cfg.team_sense_radius
        elif agent_id in self.drones:
            radius = self.cfg.drone_sense_radius
        else:
            raise KeyError(agent_id)
        me = self.agent_pos(agent_id)
        near = lambda p: chebyshev(p, me) <= radius  # noqa: E731
        out: list[Observation] = []
        for gid, c in sorted(self.civilians.items()):
            if near(tup(c.position)):
                out.append(self._observation(
                    agent_id, EntityType.CIVILIAN_GROUP, gid, tup(c.position), c.status.value,
                    self.revisions[gid],
                    {"size": c.size, "picked_up_by_team_id": c.picked_up_by_team_id},
                ))
        sp = tup(self.shelter.position)
        if near(sp):
            out.append(self._observation(
                agent_id, EntityType.SHELTER, self.shelter.shelter_id, sp, "open",
                self.shelter_revision,
                {"occupants": self.shelter.occupants, "capacity": self.shelter.capacity},
            ))
        for tid, t in sorted(self.teams.items()):
            if tid != agent_id and near(tup(t.position)):
                out.append(self._observation(
                    agent_id, EntityType.RESCUE_TEAM, tid, tup(t.position), t.status.value,
                    self.tick, {"carried_group_ids": list(t.carried_group_ids)},
                ))
        x0, y0 = me
        for y in range(y0 - radius, y0 + radius + 1):
            for x in range(x0 - radius, x0 + radius + 1):
                if (x, y) in self.flooded:
                    out.append(self._observation(
                        agent_id, EntityType.FLOOD_CELL, f"{x},{y}", (x, y), FLOODED, 0,
                    ))
        return out

    def observe_all(self) -> dict[str, list[Observation]]:
        return {aid: self.observe(aid) for aid in self.agent_ids()}

    # ---------- stepping ----------
    def step(self, proposals: list[ActionProposal]) -> StepOutcome:
        """Apply at most one proposal per agent (missing = wait), then advance the flood.

        Drones also use ActionProposal (team_id = drone_id, MOVE or WAIT only).
        Agents are processed in sorted id order, so same-tick pickup conflicts are won
        by the smaller team_id (consistent with schema.py claim ordering).
        """
        outcome = StepOutcome()
        seen: set[str] = set()
        for p in sorted(proposals, key=lambda p: p.team_id):
            if p.team_id in seen:
                outcome.results.append(self._reject(p, "more than one action this tick"))
                continue
            seen.add(p.team_id)
            outcome.results.append(self._apply(p, outcome))
        self._advance_flood(outcome)
        self.log.append(outcome)
        return outcome

    def _result(self, p: ActionProposal, status: ActionStatus, message: str | None = None,
                entity: str | None = None) -> ActionResult:
        return ActionResult(
            action_id=p.action_id,
            team_id=p.team_id,
            status=status,
            applied_at_tick=self.tick,
            resulting_position=gp(self.agent_pos(p.team_id))
            if p.team_id in self.teams or p.team_id in self.drones else None,
            affected_entity_id=entity,
            message=message,
        )

    def _reject(self, p: ActionProposal, why: str) -> ActionResult:
        return self._result(p, ActionStatus.REJECTED, why, p.target_entity_id)

    def _apply(self, p: ActionProposal, outcome: StepOutcome) -> ActionResult:
        if p.team_id in self.drones:
            return self._apply_drone(p)
        if p.team_id not in self.teams:
            return self._reject(p, "unknown agent")
        if p.action_type == ActionType.WAIT:
            return self._result(p, ActionStatus.COMPLETED)
        if p.action_type == ActionType.MOVE:
            return self._move_team(p)
        if p.action_type == ActionType.PICKUP:
            return self._pickup(p, outcome)
        return self._dropoff(p, outcome)

    def _apply_drone(self, p: ActionProposal) -> ActionResult:
        drone = self.drones[p.team_id]
        if p.action_type == ActionType.WAIT:
            return self._result(p, ActionStatus.COMPLETED)
        if p.action_type != ActionType.MOVE:
            return self._reject(p, "drones can only move or wait")
        if not drone.enabled:
            return self._reject(p, "drone disabled")
        to = tup(p.target_position)
        if not self.in_bounds(to):
            return self._reject(p, f"move out of bounds {to}")
        if chebyshev(tup(drone.position), to) > self.cfg.drone_speed:
            return self._reject(p, f"move too far {tup(drone.position)}->{to}")
        drone.position = gp(to)
        return self._result(p, ActionStatus.COMPLETED)

    def _move_team(self, p: ActionProposal) -> ActionResult:
        team = self.teams[p.team_id]
        to = tup(p.target_position)
        if not self.in_bounds(to):
            return self._reject(p, f"move out of bounds {to}")
        if manhattan(tup(team.position), to) > self.cfg.team_speed:
            return self._reject(p, f"move too far {tup(team.position)}->{to}")
        if to in self.flooded:
            return self._reject(p, f"cannot enter flooded cell {to}")
        team.position = gp(to)
        for gid in team.carried_group_ids:
            self.civilians[gid].position = gp(to)
        return self._result(p, ActionStatus.COMPLETED)

    def _update_team(self, team_id: str, **changes: Any) -> None:
        """Replace a team in one validated step (its carried fields must change together)."""
        data = self.teams[team_id].model_dump() | changes
        self.teams[team_id] = RescueTeamState.model_validate(data)

    def _set_group_status(self, outcome: StepOutcome, group: CivilianGroup,
                          status: CivilianStatus, team_id: str) -> None:
        group.status = status
        group.last_updated_at = self.now()
        self.revisions[group.group_id] += 1
        outcome.status_updates.append(CivilianStatusUpdate(
            civilian_group_id=group.group_id,
            status=status,
            changed_by_team_id=team_id,
            world_tick=self.tick,
            entity_revision=self.revisions[group.group_id],
            delivered_to_shelter_id=group.delivered_to_shelter_id,
            changed_at=self.now(),
        ))

    def _pickup(self, p: ActionProposal, outcome: StepOutcome) -> ActionResult:
        team = self.teams[p.team_id]
        group = self.civilians.get(p.target_entity_id)
        if group is None:
            return self._reject(p, f"unknown group {p.target_entity_id}")
        if group.status in (CivilianStatus.PICKED_UP, *TERMINAL):
            return self._reject(p, f"{group.group_id} is already {group.status.value}")
        if manhattan(tup(team.position), tup(group.position)) > 1:
            return self._reject(p, f"{group.group_id} not adjacent")
        if team.carried_civilians + group.size > team.capacity:
            return self._reject(p, f"not enough capacity for {group.size} people")
        self._update_team(team.team_id,
                          carried_group_ids=[*team.carried_group_ids, group.group_id],
                          carried_civilians=team.carried_civilians + group.size)
        group.picked_up_by_team_id = team.team_id
        group.position = team.position.model_copy()
        self._set_group_status(outcome, group, CivilianStatus.PICKED_UP, team.team_id)
        return self._result(p, ActionStatus.COMPLETED, entity=group.group_id)

    def _dropoff(self, p: ActionProposal, outcome: StepOutcome) -> ActionResult:
        team = self.teams[p.team_id]
        if p.target_entity_id != self.shelter.shelter_id:
            return self._reject(p, f"unknown shelter {p.target_entity_id}")
        if not team.carried_group_ids:
            return self._reject(p, "nothing to drop off")
        if manhattan(tup(team.position), tup(self.shelter.position)) > 1:
            return self._reject(p, "not at shelter")
        cap = self.shelter.capacity
        if cap is not None and self.shelter.occupants + team.carried_civilians > cap:
            return self._reject(p, "shelter full")
        for gid in team.carried_group_ids:
            group = self.civilians[gid]
            group.position = self.shelter.position.model_copy()
            group.delivered_to_shelter_id = self.shelter.shelter_id
            self._set_group_status(outcome, group, CivilianStatus.DELIVERED, team.team_id)
        self.shelter.occupants += team.carried_civilians
        self.shelter_revision += 1
        self._update_team(team.team_id, carried_group_ids=[], carried_civilians=0)
        return self._result(p, ActionStatus.COMPLETED, entity=self.shelter.shelter_id)

    def _advance_flood(self, outcome: StepOutcome) -> None:
        self.tick += 1
        newly = sorted(p for p, t in self.flood_ticks.items() if t == self.tick)
        self.flooded.update(newly)
        outcome.newly_flooded = newly
        for gid, c in sorted(self.civilians.items()):
            if (
                c.status in (CivilianStatus.AVAILABLE, CivilianStatus.REPORTED,
                             CivilianStatus.CLAIMED, CivilianStatus.UNKNOWN)
                and tup(c.position) in self.flooded
            ):
                self._set_group_status(outcome, c, CivilianStatus.LOST, FLOOD_ACTOR)
                outcome.lost_group_ids.append(gid)
        for d in self.drones.values():
            d.world_tick = self.tick

    # ---------- outputs ----------
    def score(self) -> dict[str, int]:
        cs = self.civilians
        rescued = [c for c in cs.values() if c.status == CivilianStatus.DELIVERED]
        lost = [c for c in cs.values() if c.status == CivilianStatus.LOST]
        return {
            "groups_total": len(cs),
            "groups_rescued": len(rescued),
            "groups_lost": len(lost),
            "people_total": sum(c.size for c in cs.values()),
            "people_rescued": sum(c.size for c in rescued),
            "people_lost": sum(c.size for c in lost),
        }

    def flood_update(self) -> FloodUpdate:
        return FloodUpdate(world_tick=self.tick, revision=self.tick,
                           flood_cells=[gp(p) for p in sorted(self.flooded)])

    def snapshot(self) -> WorldSnapshot:
        """Ground truth for the dashboard."""
        return WorldSnapshot(
            world_tick=self.tick,
            created_at=self.now(),
            civilian_groups=[c.model_copy(deep=True) for _, c in sorted(self.civilians.items())],
            shelters=[self.shelter.model_copy(deep=True)],
            rescue_teams=[t.model_copy(deep=True) for _, t in sorted(self.teams.items())],
            flood_cells=[gp(p) for p in sorted(self.flooded)],
            drone=next((d.model_copy(deep=True) for _, d in sorted(self.drones.items())), None),
        )
