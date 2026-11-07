"""Scenario definitions and the deterministic flood schedule (uses the shared schema.py)."""

from __future__ import annotations

import heapq
import random
from datetime import datetime, timezone

from pydantic import BaseModel

from floodnet.sim.pathing import NEIGHBOURS, Pos, gp
from schema import CivilianGroup, DroneState, RescueTeamState, Shelter


class ScenarioConfig(BaseModel):
    name: str
    seed: int = 42
    width: int = 20  # schema.GridPosition allows 0..19
    height: int = 20
    area_split_x: int = 10  # x < split is "west", otherwise "east" (neighbourhood_id)
    start_time: datetime = datetime(2026, 11, 7, 9, 0, tzinfo=timezone.utc)
    tick_seconds: int = 60  # story time per tick; used for deterministic observed_at
    river: list[Pos]  # flooded from tick 0
    high_ground: list[Pos]  # never floods
    flood_base_cost: int = 6  # ticks for water to advance one cell
    flood_noise: int = 4  # + random 0..noise ticks per cell (seeded)
    flood_slope: float = 0.0  # extra ticks per cell of horizontal distance from the river
    flood_stop_tick: int = 70  # cells reached after this never flood
    max_ticks: int = 150
    team_sense_radius: int = 2
    team_speed: int = 1
    drone_sense_radius: int = 3
    drone_speed: int = 2
    shelter: Shelter
    teams: list[RescueTeamState]
    drones: list[DroneState]
    civilians: list[CivilianGroup]


def compute_flood_ticks(cfg: ScenarioConfig) -> dict[Pos, int]:
    """Tick at which each cell floods. Cells absent from the result never flood."""
    rng = random.Random(cfg.seed)
    river_x = sum(p[0] for p in cfg.river) / max(len(cfg.river), 1)
    cost = {
        (x, y): cfg.flood_base_cost
        + rng.randint(0, cfg.flood_noise)
        + round(cfg.flood_slope * abs(x - river_x))
        for y in range(cfg.height)
        for x in range(cfg.width)
    }
    dry = set(cfg.high_ground) | {(cfg.shelter.position.x, cfg.shelter.position.y)}
    arrival: dict[Pos, int] = {}
    heap: list[tuple[int, Pos]] = [(0, p) for p in cfg.river]
    heapq.heapify(heap)
    while heap:
        t, pos = heapq.heappop(heap)
        if pos in arrival or t > cfg.flood_stop_tick:
            continue
        arrival[pos] = t
        for dx, dy in NEIGHBOURS:
            nxt = (pos[0] + dx, pos[1] + dy)
            if (
                0 <= nxt[0] < cfg.width
                and 0 <= nxt[1] < cfg.height
                and nxt not in arrival
                and nxt not in dry
            ):
                heapq.heappush(heap, (t + cost[nxt], nxt))
    return arrival


def _strip(y_from: int, width: int, height: int) -> list[Pos]:
    return [(x, y) for y in range(y_from, height) for x in range(width)]


def _team(team_id: str, pos: Pos, area: str) -> RescueTeamState:
    return RescueTeamState(team_id=team_id, position=gp(pos), capacity=6, neighbourhood_id=area)


def _group(group_id: str, pos: Pos, size: int) -> CivilianGroup:
    return CivilianGroup(group_id=group_id, position=gp(pos), size=size)


def default_scenario() -> ScenarioConfig:
    """Riverside: a river splits west/east; the southern ridge and shelter stay dry."""
    width = height = 20
    return ScenarioConfig(
        name="riverside",
        width=width,
        height=height,
        river=[(x, y) for x in (9, 10) for y in range(0, 12)],
        high_ground=_strip(16, width, height),
        flood_base_cost=5,
        flood_noise=4,
        flood_slope=1.5,
        flood_stop_tick=140,
        max_ticks=160,
        shelter=Shelter(shelter_id="shelter-1", position=gp((10, 18))),
        # Teams start on the dry southern ridge and must discover civilians.
        teams=[
            _team("team-w1", (3, 17), "west"),
            _team("team-w2", (7, 17), "west"),
            _team("team-e1", (16, 17), "east"),
            _team("team-e2", (12, 18), "east"),
        ],
        drones=[DroneState(drone_id="drone-1", position=gp((10, 17)), world_tick=0)],
        # Approximate flood deadline (tick) in comments; tune with `--flood-map`.
        civilians=[
            _group("group-1", (3, 3), 4),    # ~78
            _group("group-2", (6, 8), 3),    # ~29, urgent
            _group("group-3", (2, 12), 5),   # ~101
            _group("group-4", (15, 2), 2),   # ~61
            _group("group-5", (13, 7), 6),   # ~30, urgent
            _group("group-6", (17, 11), 3),  # ~94
            _group("group-7", (10, 15), 4),  # ~33, border group: both areas can reach it
            _group("group-8", (6, 15), 2),   # ~66
        ],
    )


def small_scenario() -> ScenarioConfig:
    """Minimal 2 teams / 3 groups scenario for first integration."""
    cfg = default_scenario()
    return cfg.model_copy(
        update={
            "name": "small",
            "teams": [t for t in cfg.teams if t.team_id in ("team-w1", "team-e1")],
            "civilians": [c for c in cfg.civilians if c.group_id in ("group-2", "group-5", "group-7")],
        },
        deep=True,
    )


SCENARIOS = {"default": default_scenario, "small": small_scenario}


def load_scenario(name: str = "default") -> ScenarioConfig:
    return SCENARIOS[name]()


def flood_map(cfg: ScenarioConfig) -> str:
    """ASCII table of flood ticks (tuning aid). '..' = never floods."""
    ticks = compute_flood_ticks(cfg)
    return "\n".join(
        " ".join(f"{ticks[(x, y)]:3d}" if (x, y) in ticks else " .." for x in range(cfg.width))
        for y in range(cfg.height)
    )
