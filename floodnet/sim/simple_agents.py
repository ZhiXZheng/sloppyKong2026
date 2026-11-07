"""Rule-based stand-in agents so the simulation can run before real agents exist.

They only use their own Observations plus memory, i.e. the same rules as real agents.
The team logic is the plan's AI fallback: "nearest known available target".
"""

from __future__ import annotations

from floodnet.models import (
    Action,
    CivilianStatus,
    Dropoff,
    Move,
    Observation,
    Pickup,
    Pos,
    Wait,
)
from floodnet.sim.pathing import bfs_path, chebyshev, manhattan

PATROLS: dict[str, list[Pos]] = {
    "west": [(4, 4), (4, 12), (7, 14), (2, 15)],
    "east": [(15, 4), (15, 12), (12, 14), (17, 15)],
    "drone": [(5, 10), (15, 10)],
}


class SimpleTeam:
    def __init__(self, agent_id: str, home_area: str, shelter: Pos, width: int, height: int):
        self.id = agent_id
        self.home_area = home_area
        self.shelter = shelter
        self.width, self.height = width, height
        self.known_flooded: set[Pos] = set()
        self.known_groups: dict[str, tuple[Pos, CivilianStatus]] = {}
        self.patrol_idx = 0

    def _passable(self, p: Pos) -> bool:
        return p not in self.known_flooded

    def _path(self, start: Pos, goal: Pos) -> list[Pos] | None:
        return bfs_path(start, goal, self._passable, self.width, self.height)

    def decide(self, obs: Observation) -> Action:
        for x, y, flooded in obs.cells:
            (self.known_flooded.add if flooded else self.known_flooded.discard)((x, y))
        seen = {c.id for c in obs.civilians}
        for c in obs.civilians:
            self.known_groups[c.id] = (c.pos, c.status)
        for gid, (pos, _) in list(self.known_groups.items()):
            if gid not in seen and chebyshev(pos, obs.pos) <= 2:
                del self.known_groups[gid]  # gone (picked up by someone else)

        if obs.carrying:
            if manhattan(obs.pos, self.shelter) <= 1:
                return Dropoff(agent_id=self.id)
            return self._step_towards(obs.pos, self.shelter)

        targets = [
            (len(path), gid, pos)
            for gid, (pos, status) in self.known_groups.items()
            if status == CivilianStatus.WAITING
            and (path := self._path(obs.pos, pos)) is not None
        ]
        if targets:
            _, gid, pos = min(targets)
            if manhattan(obs.pos, pos) <= 1:
                return Pickup(agent_id=self.id, group_id=gid)
            return self._step_towards(obs.pos, pos)

        waypoints = PATROLS[self.home_area]
        wp = waypoints[self.patrol_idx % len(waypoints)]
        if manhattan(obs.pos, wp) <= 1 or wp in self.known_flooded:
            self.patrol_idx += 1
            wp = waypoints[self.patrol_idx % len(waypoints)]
        return self._step_towards(obs.pos, wp)

    def _step_towards(self, pos: Pos, goal: Pos) -> Action:
        path = self._path(pos, goal)
        if not path or path[0] in self.known_flooded:
            self.patrol_idx += 1
            return Wait(agent_id=self.id)
        return Move(agent_id=self.id, to=path[0])


class SimpleDrone:
    def __init__(self, agent_id: str, speed: int = 2):
        self.id = agent_id
        self.speed = speed
        self.idx = 0

    def decide(self, obs: Observation) -> Action:
        wps = PATROLS["drone"]
        target = wps[self.idx % len(wps)]
        if obs.pos == target:
            self.idx += 1
            target = wps[self.idx % len(wps)]
        dx = max(-self.speed, min(self.speed, target[0] - obs.pos[0]))
        dy = max(-self.speed, min(self.speed, target[1] - obs.pos[1]))
        return Move(agent_id=self.id, to=(obs.pos[0] + dx, obs.pos[1] + dy))
