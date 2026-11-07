import pytest

from floodnet.sim.pathing import gp, tup
from floodnet.sim.runner import run
from floodnet.sim.scenario import compute_flood_ticks, default_scenario, load_scenario
from floodnet.sim.world import World
from schema import (
    ActionProposal,
    ActionStatus,
    AgentRole,
    CivilianStatus,
    EntityType,
    MessageType,
    WorldSnapshot,
    deserialize_message,
    make_message,
    parse_payload,
    serialize_message,
)


def move(agent, pos, tick=0):
    return ActionProposal(team_id=agent, action_type="move", target_position=gp(pos),
                          based_on_world_tick=tick)


def pickup(team, group, tick=0):
    return ActionProposal(team_id=team, action_type="pickup", target_entity_id=group,
                          based_on_world_tick=tick)


def dropoff(team, tick=0):
    return ActionProposal(team_id=team, action_type="drop_off", target_entity_id="shelter-1",
                          based_on_world_tick=tick)


def place(world, team, pos):
    world.teams[team].position = gp(pos)


@pytest.fixture
def world() -> World:
    return World(default_scenario())


def test_flood_is_deterministic_and_respects_terrain():
    cfg = default_scenario()
    a, b = compute_flood_ticks(cfg), compute_flood_ticks(cfg)
    assert a == b
    assert all(a[p] == 0 for p in cfg.river)
    assert not any(p in a for p in cfg.high_ground)


def test_all_scenarios_start_valid():
    for name in ("default", "small"):
        World(load_scenario(name))


def test_team_moves_one_dry_cell_only(world):
    r = world.step([move("team-w1", (3, 15))]).results[0]
    assert r.status == ActionStatus.REJECTED and tup(world.teams["team-w1"].position) == (3, 17)
    r = world.step([move("team-w1", (3, 16))]).results[0]
    assert r.status == ActionStatus.COMPLETED and tup(r.resulting_position) == (3, 16)


def test_team_cannot_enter_water(world):
    place(world, "team-w1", (8, 5))
    r = world.step([move("team-w1", (9, 5))]).results[0]
    assert r.status == ActionStatus.REJECTED and "flooded" in r.message


def test_drone_flies_over_water_at_speed_two_and_can_be_disabled(world):
    world.drones["drone-1"].position = gp((8, 5))
    world.step([move("drone-1", (10, 5))])
    assert tup(world.drones["drone-1"].position) == (10, 5)
    world.drones["drone-1"].enabled = False
    assert world.step([move("drone-1", (11, 5))]).results[0].status == ActionStatus.REJECTED


def test_pickup_carry_and_dropoff_emit_status_updates(world):
    place(world, "team-w1", (6, 16))
    out = world.step([pickup("team-w1", "group-8")])
    team, group = world.teams["team-w1"], world.civilians["group-8"]
    assert team.carried_group_ids == ["group-8"] and team.carried_civilians == group.size
    assert out.status_updates[0].status == CivilianStatus.PICKED_UP
    assert out.status_updates[0].entity_revision == 1
    place(world, "team-w1", (10, 17))
    out = world.step([dropoff("team-w1")])
    assert group.status == CivilianStatus.DELIVERED
    assert out.status_updates[0].delivered_to_shelter_id == "shelter-1"
    assert world.teams["team-w1"].carried_group_ids == []
    assert world.shelter.occupants == group.size
    assert world.score()["people_rescued"] == group.size


def test_pickup_cannot_be_duplicated(world):
    for tid in ("team-w1", "team-e2"):
        place(world, tid, (10, 16))
    out = world.step([pickup("team-w1", "group-7"), pickup("team-e2", "group-7")])
    assert world.civilians["group-7"].picked_up_by_team_id == "team-e2"  # smaller id wins
    assert {r.team_id: r.status for r in out.results}["team-w1"] == ActionStatus.REJECTED


def test_pickup_requires_adjacency_and_capacity(world):
    assert world.step([pickup("team-w1", "group-1")]).results[0].status == ActionStatus.REJECTED
    place(world, "team-w1", (6, 16))
    world.step([pickup("team-w1", "group-8")])  # 2 of 6
    place(world, "team-w1", (10, 16))
    world.step([pickup("team-w1", "group-7")])  # +4 = 6, fits
    assert world.teams["team-w1"].carried_civilians == 6
    place(world, "team-w1", (13, 8))
    r = world.step([pickup("team-w1", "group-5")]).results[0]
    assert r.status == ActionStatus.REJECTED and "capacity" in r.message


def test_dropoff_needs_shelter_id(world):
    bad = ActionProposal(team_id="team-w1", action_type="drop_off", target_entity_id="nope",
                         based_on_world_tick=0)
    assert world.step([bad]).results[0].status == ActionStatus.REJECTED


def test_waiting_group_is_lost_when_flooded_but_carried_group_is_safe(world):
    deadline = world.flood_ticks[tup(world.civilians["group-2"].position)]
    place(world, "team-w1", (13, 8))
    world.step([pickup("team-w1", "group-5")])
    while world.tick < deadline:
        world.step([])
    assert world.civilians["group-2"].status == CivilianStatus.LOST
    assert world.civilians["group-5"].status == CivilianStatus.PICKED_UP
    place(world, "team-w2", (6, 7))
    obs = [o for o in world.observe("team-w2") if o.entity.entity_id == "group-2"]
    assert obs[0].observed_status == "lost"
    snap = {c.group_id: c.status for c in world.snapshot().civilian_groups}
    assert snap["group-2"] == CivilianStatus.LOST
    place(world, "team-w2", (5, 8))  # adjacent: pickup must still be refused
    assert world.step([pickup("team-w2", "group-2")]).results[0].status == ActionStatus.REJECTED


def test_observations_are_local_and_schema_valid(world):
    obs = world.observe("team-w1")
    assert all(abs(o.position.x - 3) <= 2 and abs(o.position.y - 17) <= 2 for o in obs)
    place(world, "team-w1", (6, 14))
    groups = [o for o in world.observe("team-w1")
              if o.entity.entity_type == EntityType.CIVILIAN_GROUP]
    assert [o.entity.entity_id for o in groups] == ["group-8"]
    o = groups[0]
    assert o.observer_id == "team-w1" and o.observed_tick == 0 and o.details["size"] == 2
    msg = make_message(message_type=MessageType.OBSERVATION, sender_id="team-w1",
                       sender_role=AgentRole.RESCUE_TEAM, payload=o)
    assert parse_payload(deserialize_message(serialize_message(msg))) == o


def test_ids_and_times_are_deterministic():
    a, b = World(default_scenario()), World(default_scenario())
    assert a.observe("drone-1") == b.observe("drone-1")


def test_snapshot_is_a_valid_world_snapshot(world):
    snap = world.snapshot()
    assert WorldSnapshot.model_validate_json(snap.model_dump_json()) == snap
    msg = make_message(message_type=MessageType.WORLD_SNAPSHOT, sender_id="sim",
                       sender_role=AgentRole.SIMULATION, payload=snap)
    deserialize_message(serialize_message(msg))
    assert world.flood_update().flood_cells == snap.flood_cells


def test_full_run_terminates():
    w = run("default", show=False)
    assert w.is_done()
    s = w.score()
    assert s["groups_rescued"] + s["groups_lost"] <= s["groups_total"]
