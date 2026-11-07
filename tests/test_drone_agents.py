"""Behavioral coverage for scouting, task ownership, local execution and courier isolation."""
from concurrent.futures import Future
from unittest.mock import patch
import json
import unittest

from floodnet.sim.drone_agents import (
    Assignment, DecisionWorker, DroneAgentSystem, Evidence, RescueDecision,
    ScoutDecision, SCOUT_PROMPT, interaction_path,
)
from floodnet.sim.pathing import gp, tup, chebyshev
from schema import ActionStatus, ActionType


class ImmediatePool:
    def submit(self, fn, *args):
        f = Future()
        f.set_result(fn(*args))
        return f
    def shutdown(self, **kwargs):
        pass


class RoleProvider:
    model = 'test-claude'
    def __init__(self):
        self.calls = []
    def generate(self, prompt, timeout, output_schema, system):
        context = json.loads(prompt)
        self.calls.append(context)
        if context['role'] == 'scout':
            return dict(candidate_id=context['search_candidates'][0]['candidate_id'], explanation='Search unseen cells')
        groups = sorted(context['civilian_groups'], key=lambda g: (-g['size'], g['group_id']))
        return dict(priorities=[g['group_id'] for g in groups], explanation='Save most people using feasible routes', confidence=0.8)


class AgentSystemTests(unittest.TestCase):
    def setUp(self):
        from floodnet.server import SimManager
        self.provider = RoleProvider()
        self.manager = SimManager(drone_provider=self.provider)
        self.manager.drone_ai.close()
        self.system = self.manager.drone_ai = DroneAgentSystem(self.manager.cfg,
            provider=self.provider, pool=ImmediatePool())
        self.world, self.agents = self.manager.world, self.manager.agents
    def tearDown(self):
        self.manager.drone_ai.close()
    def group(self, gid='g', pos=(5, 15), size=3, version=(0, 0)):
        self.system.evidence.merge({gid: (pos, 'available', size)}, {gid: version})
        self.system.planner.priorities = [gid]
        self.system.planner.reason = 'Claude rescue plan'
        return gid
    def test_both_free_closest_dry_route_team_goes(self):
        gid = self.group(pos=(14, 15))
        self.system.dispatch(self.world, self.agents, False)
        self.assertEqual(self.system.assignments[gid].team_id, 'team-e1')
        self.assertEqual(self.system.assignments[gid].phase, 'pending_delivery')
        self.assertIsNone(self.system.orders['team-e1'])
    def test_both_busy_queued_then_first_free_team_goes(self):
        gid = self.group(pos=(15, 15))
        for t in self.system.teams.values():
            t['carried'] = 4
        self.system.dispatch(self.world, self.agents, False)
        self.assertNotIn(gid, self.system.assignments)
        # West becomes free first even though East would be nearer.
        self.system.teams['team-w1']['carried'] = 0
        self.system.dispatch(self.world, self.agents, False)
        self.assertEqual(self.system.assignments[gid].team_id, 'team-w1')
    def test_capacity_and_exclusive_ownership(self):
        gid = self.group(size=5)
        self.system.teams['team-w1']['capacity'] = 2
        for _ in range(5):
            self.system.dispatch(self.world, self.agents, False)
        self.assertEqual(len(self.system.assignments), 1)
        self.assertEqual(self.system.assignments[gid].team_id, 'team-e1')
    def test_no_capacity_or_safe_route_keeps_task_pending(self):
        gid = self.group(size=7)
        self.system.dispatch(self.world, self.agents, False)
        self.assertFalse(self.system.assignments)
        self.system.evidence.groups[gid] = ((5, 15), 'available', 3)
        self.system.evidence.flooded.update((x, 16) for x in range(20))
        self.system.dispatch(self.world, self.agents, False)
        self.assertFalse(self.system.assignments)
    def test_order_and_evidence_require_contact_with_team_not_old_hub(self):
        gid = self.group(pos=(5, 15))
        self.manager.set_radio(False)
        self.system.dispatch(self.world, self.agents, False)
        drone = self.world.drones['drone-1']
        drone.position = gp((5, 10))  # The obsolete courier depot.
        self.system.sense(self.world, self.agents, self.world.observe_all(), False)
        self.assertNotIn(gid, self.agents['team-w1'].known_groups)
        self.assertIsNone(self.system.orders['team-w1'])
        self.assertEqual(self.system.team_action(self.world, 'team-w1', self.agents['team-w1']).action_type, ActionType.WAIT)
        drone.position = gp((4, 17))
        self.system.sense(self.world, self.agents, self.world.observe_all(), False)
        self.assertIn(gid, self.agents['team-w1'].known_groups)
        self.assertEqual(self.system.orders['team-w1'], gid)
        self.assertGreater(self.system.delivered_count, 0)
        action = self.system.team_action(self.world, 'team-w1', self.agents['team-w1'])
        self.assertEqual(action.action_type, ActionType.MOVE)
    def test_remote_team_positions_and_discoveries_do_not_leak_in_partition(self):
        self.manager.set_radio(False)
        self.world.teams['team-w1'].position = gp((1, 1))
        self.world.drones['drone-1'].position = gp((19, 19))
        self.agents['team-w1'].known_groups['hidden'] = ((1, 2), 'available', 3)
        self.system.sense(self.world, self.agents, self.world.observe_all(), False)
        self.assertEqual(self.system.courier.positions['team-w1'], (3, 17))
        self.assertEqual(self.system.teams['team-w1']['position'], (3, 17))
        self.assertNotIn('hidden', self.system.evidence.groups)
        target = self.system.courier.destination('team-w1', (19,19), 20,20,1)
        self.assertEqual(target, (3,17))
    def test_new_sightings_update_courier_but_not_remote_busy_status(self):
        self.manager.set_radio(False)
        self.world.drones['drone-1'].position = gp((6, 17))  # Sensor range 3; contact range 1.
        self.world.teams['team-w1'].position = gp((3, 16))
        self.system.sense(self.world, self.agents, self.world.observe_all(), False)
        self.assertEqual(self.system.courier.positions['team-w1'], (3,16))
        self.assertEqual(self.system.teams['team-w1']['position'], (3,17))
    def test_stale_received_evidence_does_not_undo_terminal_status(self):
        self.group(version=(5, 2))
        self.system.evidence.merge({'g': ((5,15), 'delivered', 3)}, {'g': (6,3)})
        self.agents['team-w1'].known_groups['g'] = ((5,15), 'available', 3)
        self.agents['team-w1'].known_group_versions['g'] = (1,0)
        self.system.sense(self.world, self.agents, self.world.observe_all(), True)
        self.assertEqual(self.system.evidence.groups['g'][1], 'delivered')
        self.assertEqual(self.agents['team-w1'].known_groups['g'][1], 'delivered')
    def test_pause_does_not_scout_or_move_and_return_overrides_ai(self):
        from floodnet.server import DroneRequest, control_drone
        with patch('floodnet.server.manager', self.manager):
            control_drone(DroneRequest(action='pause'))
            self.manager.step()
            self.assertFalse(self.system.scout.covered)
            self.assertFalse(self.provider.calls)
            control_drone(DroneRequest(action='launch'))
            self.world.drones['drone-1'].position = gp((5,10))
            control_drone(DroneRequest(action='return'))
            self.manager.set_radio(False)
            for _ in range(6):
                state = self.manager.step()
        self.assertEqual(state['drone']['status'], 'idle')
        self.assertEqual(tup(self.world.drones['drone-1'].position), self.manager.drone_base)
    def test_worker_unknown_choice_invalidated_response_and_timeout(self):
        worker = self.system.scout.worker
        worker.submit(dict(role='scout', search_candidates=[dict(candidate_id='invalid')]), {'valid': (1,1)})
        self.system.scout.decide(0, (10,17), Evidence())
        self.assertIn('rejected', worker.status)
        self.assertNotEqual(self.system.scout.goal,(1,1))
        self.assertEqual(self.system.scout.decision_source,'coverage_execution')
        worker.invalidate()
        worker.submit(dict(role='scout', search_candidates=[dict(candidate_id='valid')]), {'valid': (1,1)})
        worker.invalidate()
        self.assertIsNone(worker.poll())
        self.assertNotEqual(self.system.scout.goal,(1,1))
        worker.clock = lambda: 10
        worker.pending = dict(future=Future(), deadline=1, valid=True, metadata={})
        self.assertIsNone(worker.poll())
        self.assertIn('timed out', worker.status)
        self.assertFalse(worker.submit({}, {}))
    def test_bounded_calls_reset_preserves_provider_and_clears_tasks(self):
        self.group()
        self.system.dispatch(self.world, self.agents, False)
        self.manager.reset()
        self.assertIs(self.manager.drone_ai.provider, self.provider)
        self.assertFalse(self.manager.drone_ai.assignments)
        self.assertEqual(self.manager.get_state()['tick'], 0)
    def test_end_to_end_scout_assign_pickup_deliver_and_display_actual_plan(self):
        moved = False
        for _ in range(65):
            before = {tid: tup(team.position) for tid, team in self.world.teams.items()}
            drone_before = tup(self.world.drones['drone-1'].position)
            state = self.manager.step()
            moved |= drone_before != tup(self.world.drones['drone-1'].position)
            for tid, team in self.world.teams.items():
                if before[tid] != tup(team.position):
                    self.assertNotIn(tup(team.position), self.world.flooded)
            owners = [a.team_id for a in self.system.assignments.values()]
            self.assertEqual(len(owners), len(set(owners)))
        self.assertTrue(moved)
        self.assertGreater(self.world.score()['people_rescued'], 0)
        self.assertTrue(any(c['role'] == 'scout' for c in self.provider.calls))
        self.assertTrue(any(c['role'] == 'rescue_planner' for c in self.provider.calls))
        self.assertIn('agentSystem', state['drone'])
        for prompt in self.provider.calls:
            self.assertNotIn('flood_ticks', prompt)
    def test_free_means_delivered_not_merely_picked_up(self):
        # Real scenario run: never release ownership while passengers are aboard.
        for _ in range(35):
            self.manager.step()
            for tid, team in self.world.teams.items():
                if team.carried_civilians:
                    self.assertTrue(any(a.team_id == tid for a in self.system.assignments.values()))
                    self.assertIsNotNone(self.system.orders[tid])
    def test_dry_interaction_route_never_enters_flooded_target(self):
        path = interaction_path((0,0), (2,0), {(2,0)}, 4,4)
        self.assertEqual(path, [(1,0)])
        self.assertTrue(all(p != (2,0) for p in path))


    def test_new_discovery_keeps_safe_existing_priorities_and_requests_update(self):
        self.group('a')
        self.system.planner.priorities = []
        self.system.planner.decide(self.system.planning_context(0))
        self.group('b', pos=(15,15))
        self.system.planner.priorities = []
        self.system.planner.decide(self.system.planning_context(1))
        self.assertEqual(self.system.planner.priorities, ['a'])
        self.assertEqual(self.system.planner.worker.stats['failed'],0)
        self.system.planner.decide(self.system.planning_context(2))
        self.assertEqual(set(self.system.planner.priorities), {'a','b'})

    def test_invented_planner_target_is_rejected(self):
        self.group('a')
        self.system.planner.priorities = []
        original = self.provider.generate
        self.provider.generate = lambda *args: dict(priorities=['invented'], explanation='Unknown target', confidence=0.8)
        self.system.planner.decide(self.system.planning_context(0))
        self.system.planner.decide(self.system.planning_context(1))
        self.system.dispatch(self.world,self.agents,False)
        self.assertNotIn('invented',self.system.assignments)
        self.assertIn('a',self.system.assignments)
        self.assertFalse(self.system.assignments['a'].ai_ranked)
        self.assertIn('rejected',self.system.planner.worker.status)
        self.provider.generate = original

    def test_courier_scouts_while_busy_teams_are_not_due_to_finish(self):
        self.group('g')
        for tid in self.system.teams:
            self.system.teams[tid]['carried'] = 3
        self.system.assignments['busy-west'] = Assignment('busy-west','team-w1',0,'Existing task',0.8,'active',50)
        self.system.assignments['busy-east'] = Assignment('busy-east','team-e1',0,'Existing task',0.8,'active',50)
        self.world.tick = 15
        self.system.drone_action(self.world,self.agents,False)
        self.assertEqual(self.system.mode,'scout')

    def test_api_schema_keeps_local_bounds_out_of_wire_and_validates_locally(self):
        from person_b.ai_client import claude_output_schema
        from pydantic import ValidationError
        wire = claude_output_schema(RescueDecision.model_json_schema())
        self.assertNotIn('maxItems', wire['properties']['priorities'])
        self.assertNotIn('maximum', wire['properties']['confidence'])
        with self.assertRaises(ValidationError):
            RescueDecision(priorities=['a','a'],explanation='Duplicate rescue',confidence=0.8)
        with self.assertRaises(ValidationError):
            RescueDecision(priorities=['a'],explanation='Invalid confidence',confidence=2.0)


    def test_reconnect_delivers_pending_orders_once(self):
        gid=self.group()
        self.system.dispatch(self.world,self.agents,False)
        self.assertIsNone(self.system.orders['team-w1'])
        self.system.sense(self.world,self.agents,self.world.observe_all(),True)
        self.assertEqual(self.system.orders['team-w1'],gid)
        self.system.sense(self.world,self.agents,self.world.observe_all(),True)
        self.assertEqual(len(self.system.assignments),1)
        delivered=[e for e in self.system.events if e['title']=='Rescue Order Delivered']
        self.assertEqual(len(delivered),1)

    def test_missing_credentials_do_not_start_rule_patrol(self):
        with patch('floodnet.sim.drone_agents.ClaudeProvider',side_effect=ValueError('No key')):
            system=DroneAgentSystem(self.manager.cfg,pool=ImmediatePool())
        try:
            system.sense(self.world,self.agents,self.world.observe_all(),True)
            action=system.drone_action(self.world,self.agents,True)
            self.assertEqual(action.action_type,ActionType.WAIT)
            self.assertIsNone(system.scout.goal)
            self.assertFalse(system.assignments)
            self.assertIn('API_KEY',system.scout.worker.status)
        finally:
            system.close()


    def test_full_coverage_continues_through_claude_failures(self):
        from person_b.ai_client import ClaudeAPIError
        def unavailable(*args):
            raise ClaudeAPIError('timeout',True)
        self.provider.generate=unavailable
        for _ in range(160):
            before=self.world.agent_pos('drone-1')
            self.manager.step()
            if not self.system.scout.complete:
                self.assertNotEqual(self.world.agent_pos('drone-1'),before)
            else:
                break
        self.assertTrue(self.system.scout.complete)
        self.assertEqual(len(self.system.scout.covered),400)
        self.assertEqual(self.system.scout.worker.last_error,'timeout')
        self.assertFalse(self.system.scout.worker.stats['succeeded'])

    def test_full_coverage_while_claude_request_never_completes(self):
        self.system.scout.worker.pending=dict(future=Future(),deadline=0,valid=True,metadata={})
        for _ in range(160):
            self.manager.step()
            if self.system.scout.complete:
                break
        self.assertTrue(self.system.scout.complete)
        self.assertEqual(self.system.scout.worker.stats['requests'],0)
        self.assertEqual(self.system.scout.worker.stats['failed'],1)

    def test_shelter_dropoff_immediately_reuses_free_team_during_api_outage(self):
        from person_b.ai_client import ClaudeAPIError
        def unavailable(*args):
            raise ClaudeAPIError('rate_limit',True,30)
        self.provider.generate=unavailable
        # All three real groups are observed, reachable and safe throughout this
        # regression. Two teams must perform at least three separate rescues.
        positions={'group-2':(8,16),'group-5':(12,16),'group-7':(10,15)}
        for gid,pos in positions.items():
            self.world.civilians[gid].position=gp(pos)
        self.world.flood_ticks={p:0 for p in self.world.flooded}
        assigned={tid:set() for tid in self.world.teams}
        dropoffs={tid:0 for tid in self.world.teams}
        for _ in range(50):
            self.manager.step()
            for tid,gid in self.system.orders.items():
                if gid:
                    assigned[tid].add(gid)
            for result in self.world.log[-1].results:
                if result.affected_entity_id=='shelter-1' and result.status==ActionStatus.COMPLETED:
                    dropoffs[result.team_id]+=1
            if self.world.score()['people_rescued']==13:
                break
        self.assertEqual(self.world.score()['people_rescued'],13)
        self.assertTrue(any(len(groups)>1 for groups in assigned.values()))
        self.assertTrue(any(count>1 for count in dropoffs.values()))
        self.assertTrue(all(not t.carried_civilians for t in self.world.teams.values()))

    def test_long_successful_reply_and_rate_limit_backoff_are_distinct(self):
        from person_b.ai_client import ClaudeAPIError
        now=[0.0]
        worker=DecisionWorker(self.provider,ImmediatePool(),ScoutDecision,SCOUT_PROMPT,lambda:now[0])
        original=self.provider.generate
        def slow(*args):
            now[0]+=7
            return dict(candidate_id='a',explanation='Valid slower response')
        self.provider.generate=slow
        self.assertTrue(worker.submit({}, {'a':(1,1)}))
        self.assertIsNotNone(worker.poll())
        self.assertEqual(worker.stats['failed'],0)
        def limited(*args):
            raise ClaudeAPIError('rate_limit',True,25)
        self.provider.generate=limited
        self.assertTrue(worker.submit({},{}))
        self.assertIsNone(worker.poll())
        self.assertEqual(worker.last_error,'rate_limit')
        self.assertFalse(worker.submit({},{}))
        now[0]+=24
        self.assertFalse(worker.submit({},{}))
        now[0]+=1
        self.assertTrue(worker.submit({},{}))
        worker.poll()
        self.provider.generate=original

    def test_permanent_api_failure_is_not_retried_or_exposed(self):
        from person_b.ai_client import ClaudeAPIError
        now=[0.0]
        worker=DecisionWorker(self.provider,ImmediatePool(),ScoutDecision,SCOUT_PROMPT,lambda:now[0])
        self.provider.generate=lambda *args: (_ for _ in ()).throw(ClaudeAPIError('authentication'))
        worker.submit({}, {})
        worker.poll()
        now[0]=10000
        self.assertFalse(worker.submit({},{}))
        self.assertTrue(worker.disabled)
        self.assertEqual(worker.stats['requests'],1)
        self.assertEqual(worker.stats['categories'],{'authentication':1})

    def test_only_changed_target_is_removed_from_delayed_plan(self):
        self.group('a')
        self.system.planner.priorities=[]
        self.system.planner.decide(self.system.planning_context(0))
        self.system.evidence.merge({'a':((5,15),'lost',3)},{'a':(2,1)})
        self.system.planner.decide(self.system.planning_context(1))
        self.system.dispatch(self.world,self.agents,False)
        self.assertNotIn('a',self.system.assignments)
        self.assertEqual(self.system.planner.worker.stats['failed'],0)


    def test_status_collection_cannot_starve_coverage_when_rescues_are_unreachable(self):
        # Teams are safe below a continuous water barrier. Civilian evidence stays
        # pending, so status polling must leave actual flight time for scouting.
        self.manager.set_radio(False)
        self.world.flooded.update((x,16) for x in range(20))
        self.world.flood_ticks={p:0 for p in self.world.flooded}
        self.system.evidence.flooded.update(self.world.flooded)
        self.group('group-7',(10,15),4)
        for _ in range(240):
            self.manager.step()
            if self.system.scout.complete:
                break
        self.assertTrue(self.system.scout.complete)
        self.assertEqual(len(self.system.scout.covered),400)
