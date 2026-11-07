"""Grid path helpers. Pure functions so agents can plan on their own belief maps."""

from __future__ import annotations

from collections import deque
from typing import Callable

from schema import GridPosition

Pos = tuple[int, int]

NEIGHBOURS: tuple[Pos, ...] = ((0, -1), (1, 0), (0, 1), (-1, 0))


# Validate a tuple as a protocol grid position at a simulation boundary.
def gp(pos: Pos) -> GridPosition:
    return GridPosition(x=pos[0], y=pos[1])


# Convert a protocol position to a hashable tuple for sets and path searches.
def tup(pos: GridPosition) -> Pos:
    return (pos.x, pos.y)


# Measure cardinal ground distance without allowing diagonal shortcuts.
def manhattan(a: Pos, b: Pos) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


# Measure square sensor range or per-axis drone flight distance.
def chebyshev(a: Pos, b: Pos) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def bfs_path(
    start: Pos,
    goal: Pos,
    passable: Callable[[Pos], bool],
    width: int,
    height: int,
) -> list[Pos] | None:
    """Shortest 4-neighbour path from start to goal (excluding start), or None.

    The goal itself is always allowed so agents can path onto a target cell.
    """
    if start == goal:
        return []
    prev: dict[Pos, Pos] = {start: start}
    queue = deque([start])
    while queue:
        cur = queue.popleft()
        for dx, dy in NEIGHBOURS:
            nxt = (cur[0] + dx, cur[1] + dy)
            if nxt in prev or not (0 <= nxt[0] < width and 0 <= nxt[1] < height):
                continue
            if nxt != goal and not passable(nxt):
                continue
            prev[nxt] = cur
            if nxt == goal:
                path = [nxt]
                while prev[path[-1]] != start:
                    path.append(prev[path[-1]])
                return path[::-1]
            queue.append(nxt)
    return None


# Return only the first step of a reachable route; no route means no proposed movement.
def next_step(
    start: Pos,
    goal: Pos,
    passable: Callable[[Pos], bool],
    width: int,
    height: int,
) -> Pos | None:
    path = bfs_path(start, goal, passable, width, height)
    if not path:
        return None
    return path[0]
