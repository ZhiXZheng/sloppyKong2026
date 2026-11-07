"""Grid path helpers. Pure functions so agents can plan on their own belief maps."""

from __future__ import annotations

from collections import deque
from typing import Callable

from floodnet.models import Pos

NEIGHBOURS: tuple[Pos, ...] = ((0, -1), (1, 0), (0, 1), (-1, 0))


def manhattan(a: Pos, b: Pos) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


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
