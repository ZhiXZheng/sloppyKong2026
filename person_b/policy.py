"""Deterministic four-neighbour routes and whole-group rescue policy."""

from collections import deque

from schema import CivilianStatus, EntityType, GridPosition


def route(store, start, goal, unknown_traversable=True):
    start, goal = (start.x, start.y), (goal.x, goal.y)
    blocked, known = set(), {start}
    for o in store.observations():
        if o.position is None:
            continue
        cell = (o.position.x, o.position.y)
        known.add(cell)
        if o.entity.entity_type == EntityType.FLOOD_CELL and o.details.get("traversable") is not True:
            blocked.add(cell)
    queue, previous = deque([start]), {start: None}
    while queue:
        cell = queue.popleft()
        if cell == goal:
            path = []
            while previous[cell] is not None:
                path.append(GridPosition(x=cell[0], y=cell[1]))
                cell = previous[cell]
            return list(reversed(path))
        x, y = cell
        for nxt in ((x - 1, y), (x, y - 1), (x, y + 1), (x + 1, y)):
            if not (0 <= nxt[0] < 20 and 0 <= nxt[1] < 20):
                continue
            if nxt in previous or nxt in blocked or (not unknown_traversable and nxt not in known):
                continue
            previous[nxt] = cell
            queue.append(nxt)
    return None


def candidates(store, state, excluded=(), unknown_traversable=True):
    choices = {}
    for o in store.observations(EntityType.CIVILIAN_GROUP):
        group_id = o.entity.entity_id
        size = o.details.get("size")
        if (group_id in excluded or o.position is None or type(size) is not int or size < 1
                or size > state.capacity - state.carried_civilians
                or store.claimed_by_other(group_id)):
            continue
        if o.observed_status not in (CivilianStatus.AVAILABLE, CivilianStatus.CLAIMED):
            continue
        if o.observed_status == CivilianStatus.CLAIMED and not store.own_active_claim(group_id):
            continue
        if o.details.get("picked_up_by_team_id") or o.details.get("delivered_to_shelter_id"):
            continue
        path = route(store, state.position, o.position, unknown_traversable)
        if path is not None:
            choices[group_id] = (o, path)
    return choices


def select_target(choices, current=None):
    if current in choices:
        return current
    return min(choices, key=lambda group: (len(choices[group][1]), group), default=None)


def shelter_route(store, state, unknown_traversable=True):
    choices = []
    for o in store.observations(EntityType.SHELTER):
        if o.position is None:
            continue
        capacity, occupants = o.details.get("capacity"), o.details.get("occupants")
        if capacity is not None:
            if type(capacity) is not int or type(occupants) is not int:
                continue
            if capacity - occupants < state.carried_civilians:
                continue
        path = route(store, state.position, o.position, unknown_traversable)
        if path is not None:
            choices.append((len(path), o.entity.entity_id, path))
    return min(choices, key=lambda item: item[:2]) if choices else None
