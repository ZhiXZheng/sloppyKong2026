"""Rule-based stand-in agents so the simulation can run before real agents exist.

They use only their own observations, their own state and memory, i.e. the same
inputs as real agents, and output schema.ActionProposal. The team rule is the
plan's AI fallback: "nearest known available target".
"""

from __future__ import annotations

from schema import ActionProposal, ActionType, EntityType, Observation, RescueTeamState

from floodnet.sim.pathing import Pos, bfs_path, gp, manhattan, tup

PATROLS: dict[str, list[Pos]] = {
    "west": [(4, 4), (4, 12), (7, 14), (2, 15)],
    "east": [(15, 4), (15, 12), (12, 14), (17, 15)],
    "drone": [(5, 10), (15, 10)],
}
AVAILABLE = {"available", "reported", "claimed", "unknown"}


class SimpleTeam:
    def __init__(self, team_id: str, home_area: str, shelter_id: str, shelter: Pos,
                 width: int, height: int):
        self.id = team_id
        self.home_area = home_area
        self.shelter_id = shelter_id
        self.shelter = shelter
        self.width, self.height = width, height
        self.known_flooded: set[Pos] = set()
        self.known_groups: dict[str, tuple[Pos, str, int]] = {}  # id -> (pos, status, size)
        self.patrol_idx = 0

    def _passable(self, p: Pos) -> bool:
        return p not in self.known_flooded

    def _path(self, start: Pos, goal: Pos) -> list[Pos] | None:
        return bfs_path(start, goal, self._passable, self.width, self.height)

    def _proposal(self, tick: int, action: ActionType, **kw) -> ActionProposal:
        return ActionProposal(team_id=self.id, action_type=action, based_on_world_tick=tick, **kw)

    def decide(self, tick: int, me: RescueTeamState, observations: list[Observation]
               ) -> ActionProposal:
        pos = tup(me.position)
        for o in observations:
            if o.entity.entity_type == EntityType.FLOOD_CELL:
                self.known_flooded.add(tup(o.position))
            elif o.entity.entity_type == EntityType.CIVILIAN_GROUP:
                self.known_groups[o.entity.entity_id] = (
                    tup(o.position), o.observed_status, o.details.get("size", 1))

        if me.carried_group_ids:
            if manhattan(pos, self.shelter) <= 1:
                return self._proposal(tick, ActionType.DROP_OFF, target_entity_id=self.shelter_id)
            return self._step_towards(tick, pos, self.shelter)

        targets = [
            (len(path), gid, gpos)
            for gid, (gpos, status, size) in self.known_groups.items()
            if status in AVAILABLE and size <= me.capacity
            and (path := self._path(pos, gpos)) is not None
        ]
        if targets:
            _, gid, gpos = min(targets)
            if manhattan(pos, gpos) <= 1:
                return self._proposal(tick, ActionType.PICKUP, target_entity_id=gid)
            return self._step_towards(tick, pos, gpos)

        waypoints = PATROLS[self.home_area]
        wp = waypoints[self.patrol_idx % len(waypoints)]
        if manhattan(pos, wp) <= 1 or wp in self.known_flooded:
            self.patrol_idx += 1
            wp = waypoints[self.patrol_idx % len(waypoints)]
        return self._step_towards(tick, pos, wp)

    def _step_towards(self, tick: int, pos: Pos, goal: Pos) -> ActionProposal:
        path = self._path(pos, goal)
        if not path or path[0] in self.known_flooded:
            self.patrol_idx += 1
            return self._proposal(tick, ActionType.WAIT)
        return self._proposal(tick, ActionType.MOVE, target_position=gp(path[0]))


class SimpleDrone:
    """Fixed west<->east route (the plan's fallback route)."""

    def __init__(self, drone_id: str, speed: int = 2):
        self.id = drone_id
        self.speed = speed
        self.idx = 0

    def decide(self, tick: int, pos: Pos) -> ActionProposal:
        wps = PATROLS["drone"]
        target = wps[self.idx % len(wps)]
        if pos == target:
            self.idx += 1
            target = wps[self.idx % len(wps)]
        dx = max(-self.speed, min(self.speed, target[0] - pos[0]))
        dy = max(-self.speed, min(self.speed, target[1] - pos[1]))
        return ActionProposal(team_id=self.id, action_type=ActionType.MOVE,
                              target_position=gp((pos[0] + dx, pos[1] + dy)),
                              based_on_world_tick=tick)
