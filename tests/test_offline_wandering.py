"""Offline-only random movement must preserve rescue priorities and online behavior."""
import pytest

from floodnet.sim.drone_agents import Assignment, DroneAgentSystem
from floodnet.sim.pathing import gp, manhattan, tup
from floodnet.sim.runner import build_simple_agents
from floodnet.sim.scenario import load_scenario
from floodnet.sim.world import World
from schema import ActionProposal, ActionStatus, ActionType
from tests.test_drone_agents import ImmediatePool, RoleProvider


@pytest.fixture
def simulation():
    # A fake provider and immediate executor keep these movement checks offline.
    cfg=load_scenario('small')
    world=World(cfg)
    agents=build_simple_agents(world)
    system=DroneAgentSystem(cfg,provider=RoleProvider(),pool=ImmediatePool(),clock=lambda:0)
    yield world,agents,system
    system.close()


def test_offline_idle_team_moves_one_dry_cardinal_cell(simulation):
    world,agents,system=simulation
    tid='team-w1'
    agents[tid].observe(world.observe(tid))
    start=world.agent_pos(tid)
    action=system.team_action(world,tid,agents[tid],radio=False)
    assert action.action_type==ActionType.MOVE
    assert manhattan(start,tup(action.target_position))==1
    assert tup(action.target_position) not in world.flooded
    assert 'wandering' in action.explanation
    result=world.step([action]).results[0]
    assert result.status==ActionStatus.COMPLETED
    assert world.agent_pos(tid)!=start


def test_offline_wander_uses_random_directions_not_a_fixed_route(simulation):
    world,agents,system=simulation
    # Propose repeatedly from the same dry interior cell to exercise all choices.
    targets={tup(system.team_action(world,'team-w1',agents['team-w1'],radio=False).target_position)
             for _ in range(30)}
    assert targets=={(3,16),(4,17),(3,18),(2,17)}


def test_wandering_avoids_water_and_map_edges(simulation):
    world,agents,system=simulation
    world.teams['team-w1'].position=gp((0,0))
    world.flooded.add((1,0))
    agents['team-w1'].observe(world.observe('team-w1'))
    action=system.team_action(world,'team-w1',agents['team-w1'],radio=False)
    assert tup(action.target_position)==(0,1)
    world.flooded.add((0,1))
    agents['team-w1'].observe(world.observe('team-w1'))
    assert system.team_action(world,'team-w1',agents['team-w1'],radio=False).action_type==ActionType.WAIT


def test_online_idle_team_stays_put_and_does_not_consume_wander_randomness(simulation):
    world,agents,system=simulation
    before=system._wander_rng['team-w1'].getstate()
    for _ in range(10):
        action=system.team_action(world,'team-w1',agents['team-w1'],radio=True)
        assert action.action_type==ActionType.WAIT
    assert system._wander_rng['team-w1'].getstate()==before
    assert not system.wandering


def test_team_random_streams_are_independent_and_reproducible(simulation):
    world,agents,system=simulation
    second=DroneAgentSystem(world.cfg,provider=RoleProvider(),pool=ImmediatePool(),clock=lambda:0)
    try:
        original_world_randomness=world._rng.getstate()
        for _ in range(20):
            # Extra Bravo decisions must not change Alpha's random sequence.
            for _ in range(3):
                system.team_action(world,'team-e1',agents['team-e1'],radio=False)
            a=system.team_action(world,'team-w1',agents['team-w1'],radio=False)
            b=second.team_action(world,'team-w1',agents['team-w1'],radio=False)
            assert a.target_position==b.target_position
        assert world._rng.getstate()==original_world_randomness
    finally:
        second.close()


def test_passenger_delivery_preempts_random_wandering(simulation):
    world,agents,system=simulation
    world.civilians['group-2'].position=gp((3,16))
    pickup=ActionProposal(team_id='team-w1',action_type=ActionType.PICKUP,
                          target_entity_id='group-2',based_on_world_tick=world.tick)
    assert world.step([pickup]).results[0].status==ActionStatus.COMPLETED
    agents['team-w1'].observe(world.observe('team-w1'))
    before=system._wander_rng['team-w1'].getstate()
    action=system.team_action(world,'team-w1',agents['team-w1'],radio=False)
    assert action.target_entity_id==world.shelter.shelter_id
    assert system._wander_rng['team-w1'].getstate()==before
    assert 'team-w1' not in system.wandering


def test_pending_order_allows_wandering_until_physical_delivery(simulation):
    world,agents,system=simulation
    group=world.civilians['group-2']
    system.evidence.merge({group.group_id:(tup(group.position),'available',group.size)},
                          {group.group_id:(0,0)})
    system.planner.priorities=[group.group_id]
    system.dispatch(world,agents,False)
    assert system.assignments[group.group_id].team_id=='team-w1'
    assert system.assignments[group.group_id].phase=='pending_delivery'
    action=system.team_action(world,'team-w1',agents['team-w1'],radio=False)
    assert 'wandering' in action.explanation
    world.step([action])
    # Only this actual meeting transfers the queued order and civilian report.
    world.drones['drone-1'].position=world.teams['team-w1'].position.model_copy()
    system.sense(world,agents,world.observe_all(),False)
    assert system.orders['team-w1']==group.group_id
    before=system._wander_rng['team-w1'].getstate()
    action=system.team_action(world,'team-w1',agents['team-w1'],radio=False)
    assert action.target_entity_id==group.group_id
    assert 'wandering' not in action.explanation
    assert system._wander_rng['team-w1'].getstate()==before


def test_reconnection_stops_wandering_immediately(simulation):
    world,agents,system=simulation
    assert system.team_action(world,'team-w1',agents['team-w1'],radio=False).action_type==ActionType.MOVE
    assert system.team_action(world,'team-w1',agents['team-w1'],radio=True).action_type==ActionType.WAIT
    assert 'team-w1' not in system.wandering


def test_repeated_offline_steps_never_walk_into_water(simulation):
    world,agents,system=simulation
    for _ in range(90):
        agents['team-w1'].observe(world.observe('team-w1'))
        action=system.team_action(world,'team-w1',agents['team-w1'],radio=False)
        before=world.agent_pos('team-w1')
        if action.action_type==ActionType.MOVE:
            assert tup(action.target_position) not in world.flooded
        world.step([action])
        if world.agent_pos('team-w1')!=before:
            assert world.agent_pos('team-w1') not in world.flooded
