"""Behavior checks for Claude dispatch and dashboard integration, without API calls."""
from concurrent.futures import Future
from unittest.mock import patch
import json
import unittest

from floodnet.sim.ai_drone import AIDrone, HUBS
from floodnet.sim.pathing import gp, tup
from floodnet.sim.scenario import load_scenario
from schema import ActionType


class Provider:
    model = 'test-claude'
    def __init__(self, destination='west'):
        self.destination = destination
        self.calls = 0
        self.prompts = []
    def generate(self, prompt, timeout, output_schema, system):
        self.calls += 1
        self.prompts.append(json.loads(prompt))
        return dict(destination=self.destination, explanation='Deliver fresh flood intelligence')


class ImmediatePool:
    def submit(self, fn, *args):
        future = Future()
        future.set_result(fn(*args))
        return future
    def shutdown(self, **kwargs):
        pass


class DroneTests(unittest.TestCase):
    def setUp(self):
        self.provider = Provider()
        self.now = 0
        self.controller = AIDrone(self.provider, clock=lambda: self.now)
        self.controller.pool.shutdown(wait=True)
        self.controller.pool = ImmediatePool()
        self.drone = load_scenario('small').drones[0]
        self.base = tup(self.drone.position)
    def tearDown(self):
        self.controller.close()
    def decide(self):
        return self.controller.decide(0, self.drone, False, [], self.base)
    def test_ai_destination_moves_within_speed_and_does_not_requery_in_flight(self):
        self.assertEqual(self.decide().action_type, ActionType.WAIT)
        action = self.decide()
        self.assertEqual(tup(action.target_position), (8, 15))
        for _ in range(3):
            self.drone.position = action.target_position
            action = self.decide()
        self.assertEqual(self.provider.calls, 1)
        self.assertNotIn('local_knowledge', self.provider.prompts[0])
    def test_hold_does_not_follow_rule_patrol(self):
        self.provider.destination = 'hold'
        self.decide()
        self.assertEqual(self.decide().action_type, ActionType.WAIT)
        self.assertEqual(self.provider.calls, 1)
    def test_invalid_destination_holds_and_backs_off(self):
        self.provider.destination = 'invented-hub'
        self.decide()
        self.assertEqual(self.decide().action_type, ActionType.WAIT)
        self.decide()
        self.assertEqual(self.provider.calls, 1)
        self.assertIn('unavailable', self.controller.reason)
    def test_pause_and_stale_response(self):
        self.decide()
        self.controller.invalidate()
        self.drone.enabled = False
        self.assertEqual(self.decide().action_type, ActionType.WAIT)
        self.drone.enabled = True
        self.decide()
        self.assertIsNone(self.controller.goal)
    def test_return_is_operator_override_and_stops_at_base(self):
        self.decide()
        self.controller.return_home()
        self.drone.position = gp((5, 10))
        for _ in range(5):
            action = self.decide()
            if action.target_position:
                self.drone.position = action.target_position
        self.assertEqual(tup(self.drone.position), self.base)
        self.assertFalse(self.drone.enabled)
    def test_late_response_rejected(self):
        self.decide()
        self.controller.pending['deadline'] = -1
        self.assertEqual(self.decide().action_type, ActionType.WAIT)
        self.assertIsNone(self.controller.goal)
    def test_pending_timeout_does_not_queue_more_workers(self):
        self.controller.pending = dict(future=Future(), deadline=1, valid=True)
        self.now = 2
        self.decide()
        self.assertIn('timed out', self.controller.reason)
        self.now = 20
        self.decide()
        self.assertEqual(self.provider.calls, 0)
