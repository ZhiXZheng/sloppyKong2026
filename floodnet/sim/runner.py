"""Headless runner + ASCII view: `python -m floodnet.sim [--scenario small] [--delay 0.15]`."""

from __future__ import annotations

import argparse
import time

from schema import ActionStatus, CivilianStatus

from floodnet.sim.pathing import tup
from floodnet.sim.scenario import flood_map, load_scenario
from floodnet.sim.simple_agents import SimpleDrone, SimpleTeam
from floodnet.sim.world import World


def build_simple_agents(world: World) -> dict:
    sp = tup(world.shelter.position)
    agents: dict = {}
    for t in world.teams.values():
        agents[t.team_id] = SimpleTeam(t.team_id, t.neighbourhood_id, world.shelter.shelter_id,
                                       sp, world.width, world.height)
    for d in world.drones.values():
        agents[d.drone_id] = SimpleDrone(d.drone_id, world.cfg.drone_speed)
    return agents


def step_simple(world: World, agents: dict):
    obs = world.observe_all()
    proposals = []
    for aid in world.agent_ids():
        if aid in world.teams:
            proposals.append(agents[aid].decide(world.tick, world.team_state(aid), obs[aid]))
        else:
            proposals.append(agents[aid].decide(world.tick, world.agent_pos(aid)))
    return world.step(proposals)


def render(world: World) -> str:
    grid = [["~" if (x, y) in world.flooded else "." for x in range(world.width)]
            for y in range(world.height)]
    sx, sy = tup(world.shelter.position)
    grid[sy][sx] = "S"
    for gid, c in world.civilians.items():
        x, y = tup(c.position)
        if c.status == CivilianStatus.LOST:
            grid[y][x] = "x"
        elif c.status == CivilianStatus.AVAILABLE:
            grid[y][x] = "c"
    for i, tid in enumerate(sorted(world.teams)):
        x, y = tup(world.teams[tid].position)
        grid[y][x] = str(i + 1)
    for d in world.drones.values():
        grid[d.position.y][d.position.x] = "D"
    s = world.score()
    header = (f"tick {world.tick:3d} | rescued {s['groups_rescued']}/{s['groups_total']} groups "
              f"({s['people_rescued']} people) | lost {s['groups_lost']} ({s['people_lost']} people)")
    return header + "\n" + "\n".join(" ".join(row) for row in grid)


def run(scenario: str = "default", ticks: int | None = None, delay: float = 0.0,
        show: bool = True) -> World:
    world = World(load_scenario(scenario))
    agents = build_simple_agents(world)
    limit = ticks or world.cfg.max_ticks
    while not world.is_done() and world.tick < limit:
        out = step_simple(world, agents)
        if show:
            for u in out.status_updates:
                print(f"[t{u.world_tick}] {u.civilian_group_id} {u.status.value} by {u.changed_by_team_id}")
            for r in out.results:
                if r.status == ActionStatus.REJECTED:
                    print(f"[t{r.applied_at_tick}] rejected {r.team_id}: {r.message}")
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
