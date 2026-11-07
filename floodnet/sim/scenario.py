"""Scenario definitions and the deterministic flood schedule."""

from __future__ import annotations

import heapq
import random

from pydantic import BaseModel

from floodnet.models import CivilianGroup, Drone, Pos, Shelter, Team
from floodnet.sim.pathing import NEIGHBOURS


class ScenarioConfig(BaseModel):
    name: str
    seed: int = 42
    width: int = 20
    height: int = 20
    area_split_x: int = 10  # x < split is "west", otherwise "east"
    river: list[Pos]  # flooded from tick 0
    high_ground: list[Pos]  # never floods
    flood_base_cost: int = 6  # ticks for water to advance one cell
    flood_noise: int = 4  # + random 0..noise ticks per cell (seeded)
    flood_slope: float = 0.0  # extra ticks per cell of horizontal distance from the river
    flood_stop_tick: int = 70  # cells reached after this never flood
    max_ticks: int = 150
    shelter: Shelter
    teams: list[Team]
    drones: list[Drone]
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
    dry = set(cfg.high_ground) | {cfg.shelter.pos}
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
        shelter=Shelter(id="shelter", pos=(10, 18)),
        # Teams start on the dry southern ridge and must discover civilians.
        teams=[
            Team(id="team-w1", pos=(3, 17), home_area="west"),
            Team(id="team-w2", pos=(7, 17), home_area="west"),
            Team(id="team-e1", pos=(16, 17), home_area="east"),
            Team(id="team-e2", pos=(12, 18), home_area="east"),
        ],
        drones=[Drone(id="drone-1", pos=(10, 17))],
        # Approximate flood deadline (tick) in comments; tune with `--flood-map`.
        civilians=[
            CivilianGroup(id="c1", pos=(3, 3), size=4),    # ~78
            CivilianGroup(id="c2", pos=(6, 8), size=3),    # ~29, urgent
            CivilianGroup(id="c3", pos=(2, 12), size=5),   # ~101
            CivilianGroup(id="c4", pos=(15, 2), size=2),   # ~61
            CivilianGroup(id="c5", pos=(13, 7), size=6),   # ~30, urgent
            CivilianGroup(id="c6", pos=(17, 11), size=3),  # ~94
            CivilianGroup(id="c7", pos=(10, 15), size=4),  # ~33, border group: both areas can reach it
            CivilianGroup(id="c8", pos=(6, 15), size=2),   # ~66
        ],
    )


def small_scenario() -> ScenarioConfig:
    """Minimal 2 teams / 3 groups scenario for first integration."""
    cfg = default_scenario()
    return cfg.model_copy(
        update={
            "name": "small",
            "teams": [t for t in cfg.teams if t.id in ("team-w1", "team-e1")],
            "civilians": [c for c in cfg.civilians if c.id in ("c2", "c5", "c7")],
        },
        deep=True,
    )


SCENARIOS = {"default": default_scenario, "small": small_scenario}


def load_scenario(name: str = "default") -> ScenarioConfig:
    return SCENARIOS[name]()


def flood_map(cfg: ScenarioConfig) -> str:
    """ASCII table of flood ticks (tuning aid). '..' = never floods."""
    ticks = compute_flood_ticks(cfg)
    rows = []
    for y in range(cfg.height):
        rows.append(" ".join(f"{ticks[(x, y)]:3d}" if (x, y) in ticks else " .." for x in range(cfg.width)))
    return "\n".join(rows)
