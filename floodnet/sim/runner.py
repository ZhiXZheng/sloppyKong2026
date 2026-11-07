"""ASCII live view + headless runner: `python -m floodnet.sim [--scenario small] [--delay 1]`."""

from __future__ import annotations

import argparse
import shutil
import sys
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
    teams = "  ".join(f"{i + 1}={tid}" for i, tid in enumerate(sorted(world.teams)))
    legend = (f"teams: {teams} | D=drone S=shelter ({world.shelter.occupants} people inside) "
              "c=waiting x=lost ~=flood")
    return header + "\n" + legend + "\n" + "\n".join(" ".join(row) for row in grid)


def _frame(world: World, recent: list[str]) -> str:
    board = render(world)
    rows = shutil.get_terminal_size((80, 40)).lines
    room = rows - board.count("\n") - 3  # keep the frame within the window so it never scrolls
    events = recent[-room:] if room > 0 else []
    return board + ("\nrecent events:\n" + "\n".join(events) if events else "")


def run(scenario: str = "default", ticks: int | None = None, delay: float = 0.0,
        show: bool = True) -> World:
    """delay > 0 in a terminal: live view redrawn every tick. Otherwise print the log, then the final map."""
    world = World(load_scenario(scenario))
    agents = build_simple_agents(world)
    limit = ticks or world.cfg.max_ticks
    live = show and delay > 0 and sys.stdout.isatty()
    recent: list[str] = []
    if live:
        sys.stdout.write("\033[?1049h\033[?25l")  # alternate screen, hide cursor
    try:
        while not world.is_done() and world.tick < limit:
            out = step_simple(world, agents)
            lines = [f"[t{u.world_tick}] {u.civilian_group_id} {u.status.value} by {u.changed_by_team_id}"
                     for u in out.status_updates]
            lines += [f"[t{r.applied_at_tick}] rejected {r.team_id}: {r.message}"
                      for r in out.results if r.status == ActionStatus.REJECTED]
            recent = (recent + lines)[-8:]
            if live:
                sys.stdout.write("\033[H\033[J" + _frame(world, recent))
                sys.stdout.flush()
                time.sleep(delay)
            elif show:
                for line in lines:
                    print(line)
    except KeyboardInterrupt:
        pass
    finally:
        if live:
            sys.stdout.write("\033[?25h\033[?1049l")  # restore normal screen and cursor
            sys.stdout.flush()
    if show:
        print(render(world) + ("\nrecent events:\n" + "\n".join(recent) if live and recent else ""))
    return world


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--scenario", default="default")
    p.add_argument("--ticks", type=int)
    p.add_argument("--delay", type=float, default=0.5,
                   help="seconds per tick in the live view (default 0.5; 0 = instant, log only)")
    p.add_argument("--flood-map", action="store_true", help="print flood tick per cell and exit")
    args = p.parse_args()
    if args.flood_map:
        print(flood_map(load_scenario(args.scenario)))
        return
    run(args.scenario, args.ticks, args.delay)


if __name__ == "__main__":
    main()
