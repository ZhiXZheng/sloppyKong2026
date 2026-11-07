import unittest

from schema import (
    ActionResult, ActionType, AgentRole, ClaimStatus, EntityType, MessageEnvelope,
    MessageType, TaskClaim, TaskClaimResolution,
)
from person_b.beliefs import BeliefStore
from person_b.controller import AISettings, RescueController
from person_b.demo import border_conflict, run_comparison
from person_b.policy import candidates, route, select_target
from person_b.runtime import Runtime
from person_b.tests.helpers import observation, state


def claim(team="b", group="g", tick=0, **changes):
    runtime = Runtime(f"claim/{team}/{group}")
    data = dict(claim_id=runtime.new_id("claim"), team_id=team, civilian_group_id=group,
                claimed_at_tick=tick, claimed_at=runtime.timestamp(tick))
    return TaskClaim(**(data | changes))


def resolution(winner=None, version=1, tick=2, status="confirmed", **changes):
    data = dict(civilian_group_id="g", winning_team_id=winner.team_id if winner else None,
                winning_claim_id=winner.claim_id if winner else None,
                resolved_status=status, resolution_reason="test", resolution_version=version,
                resolved_at_tick=tick, resolved_at=Runtime().timestamp(tick))
    return TaskClaimResolution(**(data | changes))


class BeliefTests(unittest.TestCase):
    def test_duplicates_stale_and_revision_order(self):
        store = BeliefStore("a")
        new = observation(tick=4, revision=2)
        self.assertTrue(store.observe(new))
        version = store.version
        self.assertFalse(store.observe(new))
        self.assertFalse(store.observe(observation(tick=9, revision=1)))
        self.assertEqual(store.version, version)
        self.assertTrue(store.observe(observation(tick=4, revision=2, observer="zzz")))
        self.assertEqual(store.get(EntityType.CIVILIAN_GROUP, "g").observer_id, "zzz")

    def test_snapshot_mutation_does_not_change_store(self):
        store = BeliefStore("a")
        original = observation()
        store.observe(original)
        original.details["size"] = 99
        snapshot = store.snapshot(3)
        snapshot.observations[0].position.x = 18
        snapshot.observations[0].details["size"] = 42
        current = store.get(EntityType.CIVILIAN_GROUP, "g")
        self.assertEqual(current.position.x, 1)
        self.assertEqual(current.details["size"], 1)
        update = store.updates(3, Runtime().timestamp)[0]
        self.assertEqual(update.source_observed_at, current.observed_at)
        self.assertEqual(update.source_entity_revision, current.entity_revision)

    def test_terminal_claim_and_resolution_tombstones(self):
        store = BeliefStore("a")
        winning, losing = claim("a"), claim("b")
        store.merge_claim(winning)
        store.merge_claim(losing)
        res = resolution(winning, conflicting_claim_ids=[winning.claim_id, losing.claim_id])
        self.assertTrue(store.resolve(res))
        self.assertFalse(store.resolve(res))
        self.assertFalse(store.merge_claim(losing.model_copy(update={"claim_version": 20})))
        self.assertFalse(store.claimed_by_other("g"))
        self.assertEqual(store.own_active_claim("g").status, ClaimStatus.CONFIRMED)

    def test_resolution_before_claim_retains_winner(self):
        store = BeliefStore("a")
        winning = claim("a")
        store.resolve(resolution(winning))
        self.assertTrue(store.merge_claim(winning))
        self.assertEqual(store.own_active_claim("g").status, ClaimStatus.CONFIRMED)
        self.assertFalse(store.merge_claim(claim("b")))

    def test_completed_resolution_never_rolls_back(self):
        store = BeliefStore("a")
        store.resolve(resolution(status="completed"))
        self.assertFalse(store.resolve(resolution(claim("a"), version=2)))
        self.assertTrue(store.claimed_by_other("g"))

    def test_released_winner_does_not_block_future_work(self):
        store = BeliefStore("a")
        winning = claim("b")
        store.merge_claim(winning)
        store.resolve(resolution(winning))
        self.assertTrue(store.claimed_by_other("g"))
        store.merge_claim(winning.model_copy(update={"status": ClaimStatus.RELEASED, "claim_version": 2}))
        self.assertFalse(store.claimed_by_other("g"))

    def test_expiry_is_a_local_tombstone(self):
        store = BeliefStore("a")
        expiring = claim("b", expires_at=Runtime().timestamp(2))
        store.merge_claim(expiring)
        self.assertTrue(store.claimed_by_other("g"))
        store.expire(Runtime().timestamp(2))
        self.assertFalse(store.claimed_by_other("g"))
        version = store.version
        store.expire(Runtime().timestamp(3))
        self.assertEqual(store.version, version)
        self.assertFalse(store.merge_claim(expiring.model_copy(update={"claim_version": 10})))


class PolicyTests(unittest.TestCase):
    def test_eligibility_and_tie_break(self):
        store = BeliefStore("a")
        for o in (observation("b"), observation("a"), observation("terminal", status="rescued"),
                  observation("unknown", status="unknown"), observation("oversized", details={"size": 4}),
                  observation("missing", details={}), observation("claimed", status="claimed"),
                  observation("owned", details={"size": 1, "picked_up_by_team_id": "b"})):
            store.observe(o)
        choices = candidates(store, state())
        self.assertEqual(set(choices), {"a", "b"})
        self.assertEqual(select_target(choices), "a")
        self.assertEqual(select_target(choices, "b"), "b")
        store.merge_claim(claim("b", "a"))
        self.assertNotIn("a", candidates(store, state()))

    def test_bfs_avoids_known_flood(self):
        store = BeliefStore("a")
        store.observe(observation("flood", kind=EntityType.FLOOD_CELL, details={"traversable": False}))
        path = route(store, state().position, observation(x=2).position)
        self.assertEqual(len(path), 4)
        self.assertNotIn((1, 0), [(p.x, p.y) for p in path])
        self.assertIsNone(route(store, state().position, observation(x=2).position, False))


class ControllerTests(unittest.TestCase):
    def controller(self):
        controller = RescueController("a", settings=AISettings(False))
        controller.observe([observation(), observation("shelter", x=0,
            kind=EntityType.SHELTER, details={"capacity": None, "occupants": 0})])
        return controller

    def complete(self, controller, decision, status="completed"):
        result = ActionResult(action_id=decision.action.action_id, team_id="a", status=status,
                              applied_at_tick=decision.action.based_on_world_tick)
        controller.apply_result(result)
        return result

    def test_whole_rescue_and_duplicate_result(self):
        c = self.controller()
        decision = c.step(state(), False, 0, 0)
        self.assertEqual(decision.action.action_type, ActionType.MOVE)
        self.assertEqual(len(decision.outbound), 1)
        self.complete(c, decision)
        decision = c.step(state(x=1), False, 1, 1)
        self.assertEqual(decision.action.action_type, ActionType.PICKUP)
        result = self.complete(c, decision)
        version = c.beliefs.version
        c.apply_result(result)
        self.assertEqual(c.beliefs.version, version)
        decision = c.step(state(x=1, carried_civilians=1, carried_group_ids=["g"]), False, 2, 2)
        self.assertEqual(decision.action.target_position.x, 0)
        self.complete(c, decision)
        decision = c.step(state(carried_civilians=1, carried_group_ids=["g"]), False, 3, 3)
        self.assertEqual(decision.action.action_type, ActionType.DROP_OFF)
        self.complete(c, decision)
        self.assertEqual(c.step(state(), False, 4, 4).action.action_type, ActionType.WAIT)

    def test_accepted_is_not_completed_and_rejection_not_pickup(self):
        c = self.controller()
        decision = c.step(state(x=1), False, 0, 0)
        self.assertEqual(decision.action.action_type, ActionType.PICKUP)
        self.complete(c, decision, "accepted")
        self.assertEqual(c.step(state(x=1), False, 1, 1).action.action_type, ActionType.WAIT)
        self.complete(c, decision, "rejected")
        self.assertNotIn("g", c._completed_groups)
        self.assertIsNotNone(c.beliefs.own_active_claim("g"))

    def test_unrelated_results_are_ignored(self):
        c = self.controller()
        decision = c.step(state(x=1), False, 0, 0)
        c.apply_result(ActionResult(action_id=Runtime().new_id("unknown"), team_id="a",
                                   status="completed", applied_at_tick=0))
        self.assertEqual(c._outstanding.action_id, decision.action.action_id)

    def test_no_global_snapshot_knowledge(self):
        from schema import WorldSnapshot
        c = RescueController("a")
        payload = WorldSnapshot(world_tick=0, civilian_groups=[{
            "group_id": "secret", "position": {"x": 1, "y": 1}, "size": 1}])
        c.receive([MessageEnvelope(message_type=MessageType.WORLD_SNAPSHOT,
            sender_id="sim", sender_role=AgentRole.SIMULATION, payload=payload.model_dump(mode="json"))])
        self.assertEqual(c.beliefs.observations(), [])

    def test_local_observations_published_but_received_ones_not_rebroadcast(self):
        c = RescueController("a")
        local = observation(observer="a")
        c.observe([local, local])
        decision = c.step(state(), False, 0, 0)
        observations = [m for m in decision.outbound if m.message_type == MessageType.OBSERVATION]
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].payload["observer_id"], "a")
        other = RescueController("b")
        other.receive(observations)
        decision = other.step(state(team="b"), False, 0, 0)
        self.assertFalse(any(m.message_type == MessageType.OBSERVATION for m in decision.outbound))

    def test_status_updates_retain_known_size_and_location(self):
        from schema import CivilianStatusUpdate
        c = self.controller()
        update = CivilianStatusUpdate(civilian_group_id="g", status="available", changed_by_team_id="b",
                                      world_tick=1, entity_revision=1)
        c.receive([MessageEnvelope(message_type=MessageType.CIVILIAN_STATUS_UPDATE,
            sender_id="sim", sender_role=AgentRole.SIMULATION, payload=update.model_dump(mode="json"))])
        known = c.beliefs.get(EntityType.CIVILIAN_GROUP, "g")
        self.assertEqual(known.details["size"], 1)
        self.assertEqual(known.position.x, 1)
        self.assertFalse(known.details.get("picked_up_by_team_id"))

    def test_teams_are_independent_and_messages_deduplicated(self):
        a, b = RescueController("a"), RescueController("b")
        item = observation()
        envelope = MessageEnvelope(message_type=MessageType.OBSERVATION, sender_id="sensor",
            sender_role=AgentRole.RESCUE_TEAM, payload=item.model_dump(mode="json"))
        a.receive([envelope, envelope])
        self.assertEqual(a.beliefs.version, 2)
        self.assertEqual(b.step(state(team="b"), False, 0, 0).action.action_type, ActionType.WAIT)
        self.assertEqual(a.step(state(), False, 0, 0).action.action_type, ActionType.MOVE)

    def test_claim_loss_after_pickup_does_not_stop_delivery(self):
        c = self.controller()
        decision = c.step(state(x=1), False, 0, 0)
        self.complete(c, decision)
        c.beliefs.resolve(resolution(claim("b")))
        decision = c.step(state(x=1, carried_civilians=1, carried_group_ids=["g"]), True, 1, 1)
        self.assertEqual(decision.action.action_type, ActionType.MOVE)
        self.assertEqual(decision.action.target_position.x, 0)

    def test_demo_comparison_and_reproducibility(self):
        on, off = run_comparison(True), run_comparison(False)
        self.assertEqual((on["rescued"], off["rescued"]), (3, 2))
        self.assertEqual(on, run_comparison(True))
        self.assertEqual(border_conflict(), {"a": "border", "b": None})
        pickups = [a["target_entity_id"] for a in on["actions"] if a["action_type"] == "pickup"]
        self.assertEqual(len(pickups), len(set(pickups)))


if __name__ == "__main__":
    unittest.main()
