"""Headless runner + ASCII view: `python -m floodnet.sim [--scenario small] [--ticks N]`."""

from __future__ import annotations

import argparse
import time

from floodnet.models import CivilianStatus
from floodnet.sim.scenario import flood_map, load_scenario
from floodnet.sim.simple_agents import SimpleDrone, SimpleTeam
from floodnet.sim.world import World


def build_simple_agents(world: World) -> dict:
    agents: dict = {}
    for t in world.teams.values():
        agents[t.id] = SimpleTeam(t.id, t.home_area, world.shelter.pos, world.width, world.height)
    for d in world.drones.values():
        agents[d.id] = SimpleDrone(d.id, d.speed)
    return agents


def render(world: World) -> str:
    grid = [["~" if (x, y) in world.flooded else "." for x in range(world.width)]
            for y in range(world.height)]
    sx, sy = world.shelter.pos
    grid[sy][sx] = "S"
    for c in world.civilians.values():
        if c.status == CivilianStatus.WAITING:
            grid[c.pos[1]][c.pos[0]] = "c"
        elif c.status == CivilianStatus.LOST:
            grid[c.pos[1]][c.pos[0]] = "x"
    for i, t in enumerate(sorted(world.teams)):
        x, y = world.teams[t].pos
        grid[y][x] = str(i + 1)
    for d in world.drones.values():
        grid[d.pos[1]][d.pos[0]] = "D"
    s = world.score()
    header = (f"tick {world.tick:3d} | rescued {s.groups_rescued}/{s.groups_total} groups "
              f"({s.people_rescued} people) | lost {s.groups_lost} ({s.people_lost} people)")
    return header + "\n" + "\n".join(" ".join(row) for row in grid)


def run(scenario: str = "default", ticks: int | None = None, delay: float = 0.0,
        show: bool = True) -> World:
    world = World(load_scenario(scenario))
    agents = build_simple_agents(world)
    limit = ticks or world.cfg.max_ticks
    while not world.is_done() and world.tick < limit:
        obs = world.observe_all()
        actions = [agents[aid].decide(obs[aid]) for aid in world.agent_ids()]
        for e in world.step(actions):
            if show and e.kind in ("picked_up", "rescued", "lost", "rejected"):
                print(f"[t{e.tick}] {e.kind} {e.agent_id or ''} {e.group_id or ''} {e.detail}")
        if show and delay:
            print("\033[2J\033[H" + render(world))
            time.sleep(delay)
    if show:
        print(render(world))
    return world


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--scenario", default="default")
    p.add_argument("--ticks", type=int)
    p.add_argument("--delay", type=float, default=0.0, help="seconds per tick for live view")
    p.add_argument("--flood-map", action="store_true", help="print flood tick per cell and exit")
    args = p.parse_args()
    if args.flood_map:
        print(flood_map(load_scenario(args.scenario)))
        return
    run(args.scenario, args.ticks, args.delay)


if __name__ == "__main__":
    main()
