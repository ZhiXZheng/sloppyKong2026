"""Ground-truth world: grid, flood, movement, pickup, drop-off and scoring.

Agents must only learn about the world through `observe()`; they change it only by
submitting actions to `step()`. Every action is validated here, so a bad AI
recommendation can never break the simulation rules.
"""

from __future__ import annotations

from typing import Any

from floodnet.models import (
    Action,
    CivilianGroup,
    CivilianStatus,
    Drone,
    Dropoff,
    Event,
    Move,
    Observation,
    Pickup,
    Pos,
    Score,
    SeenAgent,
    SeenCivilian,
    Team,
    Wait,
)
from floodnet.sim.pathing import chebyshev, manhattan
from floodnet.sim.scenario import ScenarioConfig, compute_flood_ticks


class World:
    def __init__(self, cfg: ScenarioConfig):
        self.cfg = cfg
        self.width = cfg.width
        self.height = cfg.height
        self.tick = 0
        self.flood_ticks = compute_flood_ticks(cfg)
        self.flooded: set[Pos] = {p for p, t in self.flood_ticks.items() if t <= 0}
        self.shelter = cfg.shelter.model_copy()
        self.teams: dict[str, Team] = {t.id: t.model_copy() for t in cfg.teams}
        self.drones: dict[str, Drone] = {d.id: d.model_copy() for d in cfg.drones}
        self.civilians: dict[str, CivilianGroup] = {
            c.id: c.model_copy() for c in cfg.civilians
        }
        self.events: list[Event] = []
        for c in self.civilians.values():
            if c.pos in self.flooded:
                raise ValueError(f"civilian group {c.id} starts in water at {c.pos}")
        for t in self.teams.values():
            if t.pos in self.flooded:
                raise ValueError(f"team {t.id} starts in water at {t.pos}")

    # ---------- queries ----------
    def in_bounds(self, pos: Pos) -> bool:
        return 0 <= pos[0] < self.width and 0 <= pos[1] < self.height

    def is_flooded(self, pos: Pos) -> bool:
        return pos in self.flooded

    def area_of(self, pos: Pos) -> str:
        return "west" if pos[0] < self.cfg.area_split_x else "east"

    def agent_pos(self, agent_id: str) -> Pos:
        if agent_id in self.teams:
            return self.teams[agent_id].pos
        return self.drones[agent_id].pos

    def agent_ids(self) -> list[str]:
        return sorted(self.teams) + sorted(self.drones)

    def is_done(self) -> bool:
        if self.tick >= self.cfg.max_ticks:
            return True
        return all(
            c.status in (CivilianStatus.RESCUED, CivilianStatus.LOST)
            for c in self.civilians.values()
        )

    # ---------- sensing ----------
    def observe(self, agent_id: str) -> Observation:
        if agent_id in self.teams:
            me = self.teams[agent_id]
            radius, carrying = me.sense_radius, me.carrying
        else:
            me = self.drones[agent_id]
            radius, carrying = me.sense_radius, None
        x0, y0 = me.pos
        cells = [
            (x, y, (x, y) in self.flooded)
            for y in range(y0 - radius, y0 + radius + 1)
            for x in range(x0 - radius, x0 + radius + 1)
            if self.in_bounds((x, y))
        ]
        civilians = [
            SeenCivilian(id=c.id, pos=c.pos, size=c.size, status=c.status)
            for c in self.civilians.values()
            if c.status in (CivilianStatus.WAITING, CivilianStatus.LOST)
            and chebyshev(c.pos, me.pos) <= radius
        ]
        agents = [
            SeenAgent(id=a.id, pos=a.pos, kind="team" if a.id in self.teams else "drone")
            for a in [*self.teams.values(), *self.drones.values()]
            if a.id != agent_id and chebyshev(a.pos, me.pos) <= radius
        ]
        shelter = (
            self.shelter.pos if chebyshev(self.shelter.pos, me.pos) <= radius else None
        )
        return Observation(
            tick=self.tick,
            agent_id=agent_id,
            pos=me.pos,
            area=self.area_of(me.pos),
            carrying=carrying,
            cells=cells,
            civilians=civilians,
            agents=agents,
            shelter=shelter,
        )

    def observe_all(self) -> dict[str, Observation]:
        return {aid: self.observe(aid) for aid in self.agent_ids()}

    # ---------- stepping ----------
    def step(self, actions: list[Action]) -> list[Event]:
        """Apply one action per agent (missing = wait), then advance the flood by one tick."""
        events = self._apply_actions(actions)
        events += self._advance_flood()
        self.events.extend(events)
        return events

    def _apply_actions(self, actions: list[Action]) -> list[Event]:
        by_agent: dict[str, Action] = {}
        events: list[Event] = []
        for a in actions:
            if a.agent_id in by_agent:
                events.append(self._reject(a.agent_id, "more than one action this tick"))
                continue
            by_agent[a.agent_id] = a
        for agent_id in sorted(by_agent):
            action = by_agent[agent_id]
            if agent_id not in self.teams and agent_id not in self.drones:
                events.append(self._reject(agent_id, "unknown agent"))
                continue
            if isinstance(action, Move):
                events.append(self._move(action))
            elif isinstance(action, Pickup):
                events.append(self._pickup(action))
            elif isinstance(action, Dropoff):
                events.append(self._dropoff(action))
            elif isinstance(action, Wait):
                pass
        return [e for e in events if e is not None]

    def _reject(self, agent_id: str, why: str) -> Event:
        return Event(tick=self.tick, kind="rejected", agent_id=agent_id, detail=why)

    def _move(self, a: Move) -> Event | None:
        to = tuple(a.to)
        if not self.in_bounds(to):
            return self._reject(a.agent_id, f"move out of bounds {to}")
        if a.agent_id in self.teams:
            team = self.teams[a.agent_id]
            if manhattan(team.pos, to) > team.speed:
                return self._reject(a.agent_id, f"move too far {team.pos}->{to}")
            if to in self.flooded:
                return self._reject(a.agent_id, f"cannot enter flooded cell {to}")
            team.pos = to
            if team.carrying:
                self.civilians[team.carrying].pos = to
        else:
            drone = self.drones[a.agent_id]
            if chebyshev(drone.pos, to) > drone.speed:
                return self._reject(a.agent_id, f"move too far {drone.pos}->{to}")
            drone.pos = to
        return None

    def _pickup(self, a: Pickup) -> Event:
        team = self.teams.get(a.agent_id)
        group = self.civilians.get(a.group_id)
        if team is None:
            return self._reject(a.agent_id, "only teams can pick up")
        if group is None:
            return self._reject(a.agent_id, f"unknown group {a.group_id}")
        if team.carrying:
            return self._reject(a.agent_id, f"already carrying {team.carrying}")
        if group.status != CivilianStatus.WAITING:
            return self._reject(a.agent_id, f"{group.id} is {group.status.value}")
        if manhattan(team.pos, group.pos) > 1:
            return self._reject(a.agent_id, f"{group.id} not adjacent")
        group.status = CivilianStatus.PICKED_UP
        group.carried_by = team.id
        group.pos = team.pos
        team.carrying = group.id
        return Event(tick=self.tick, kind="picked_up", agent_id=team.id, group_id=group.id)

    def _dropoff(self, a: Dropoff) -> Event:
        team = self.teams.get(a.agent_id)
        if team is None or not team.carrying:
            return self._reject(a.agent_id, "nothing to drop off")
        if manhattan(team.pos, self.shelter.pos) > 1:
            return self._reject(a.agent_id, "not at shelter")
        group = self.civilians[team.carrying]
        group.status = CivilianStatus.RESCUED
        group.carried_by = None
        group.pos = self.shelter.pos
        group.resolved_tick = self.tick
        self.shelter.occupants += group.size
        team.carrying = None
        return Event(tick=self.tick, kind="rescued", agent_id=team.id, group_id=group.id,
                     detail=f"{group.size} people")

    def _advance_flood(self) -> list[Event]:
        self.tick += 1
        newly = {p for p, t in self.flood_ticks.items() if t == self.tick}
        self.flooded |= newly
        events: list[Event] = []
        for c in self.civilians.values():
            if c.status == CivilianStatus.WAITING and c.pos in newly:
                c.status = CivilianStatus.LOST
                c.resolved_tick = self.tick
                events.append(Event(tick=self.tick, kind="lost", group_id=c.id,
                                    detail=f"{c.size} people"))
        if newly:
            events.append(Event(tick=self.tick, kind="flooded", detail=f"{len(newly)} cells"))
        return events

    # ---------- outputs ----------
    def score(self) -> Score:
        cs = list(self.civilians.values())
        rescued = [c for c in cs if c.status == CivilianStatus.RESCUED]
        lost = [c for c in cs if c.status == CivilianStatus.LOST]
        return Score(
            groups_total=len(cs),
            groups_rescued=len(rescued),
            groups_lost=len(lost),
            people_total=sum(c.size for c in cs),
            people_rescued=sum(c.size for c in rescued),
            people_lost=sum(c.size for c in lost),
        )

    def snapshot(self) -> dict[str, Any]:
        """JSON-safe ground-truth state for the dashboard."""
        return {
            "tick": self.tick,
            "width": self.width,
            "height": self.height,
            "area_split_x": self.cfg.area_split_x,
            "flooded": sorted(self.flooded),
            "shelter": self.shelter.model_dump(mode="json"),
            "teams": [t.model_dump(mode="json") for t in self.teams.values()],
            "drones": [d.model_dump(mode="json") for d in self.drones.values()],
            "civilians": [c.model_dump(mode="json") for c in self.civilians.values()],
            "score": self.score().model_dump(),
            "done": self.is_done(),
        }
