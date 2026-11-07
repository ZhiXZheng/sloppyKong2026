# Regress protocol compatibility, validation, provenance, and serialization boundaries.
import json
import unittest
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import ValidationError

import schema as s


class SchemaTests(unittest.TestCase):
    def observation(self, **changes):
        data = dict(observer_id="team-a", entity=dict(entity_type="civilian_group",
                    entity_id="group-1"), observed_at=datetime.now(timezone.utc),
                    observed_tick=2, entity_revision=1)
        return s.Observation(**(data | changes))

    def message(self):
        return s.make_message(message_type=s.MessageType.OBSERVATION,
                              sender_id="team-a", sender_role=s.AgentRole.RESCUE_TEAM,
                              payload=self.observation())

    def test_registry_complete(self):
        self.assertEqual(set(s.MessageType), set(s.PAYLOAD_MODELS))

    def test_enum_error_is_validation_error(self):
        for action in ("pickup", "drop_off", "move"):
            with self.subTest(action=action), self.assertRaises(ValidationError):
                s.ActionProposal(team_id="a", action_type=action, based_on_world_tick=0)
        action = s.ActionProposal(team_id="a", action_type="wait", based_on_world_tick=0)
        self.assertIs(action.action_type, s.ActionType.WAIT)

    def test_invalid_payload_at_receive_boundary(self):
        raw = json.loads(s.serialize_message(self.message()))
        raw["payload"]["observed_tick"] = -1
        with self.assertRaises(ValidationError):
            s.deserialize_message(json.dumps(raw))

    def test_relay_preserves_identity_and_provenance(self):
        original = self.message()
        packet = s.CourierPacket(drone_id="drone", source_neighbourhood="a",
            destination_neighbourhood="b", messages=[s.RelayedMessage(
                envelope=original, original_sender_id="team-a")])
        outer = s.make_message(message_type=s.MessageType.COURIER_PACKET,
            sender_id="drone", sender_role=s.AgentRole.COURIER_DRONE, payload=packet)
        received = s.parse_payload(s.deserialize_message(s.serialize_message(outer)))
        self.assertEqual(received.messages[0].envelope, original)
        raw = json.loads(s.serialize_message(outer))
        raw["payload"]["messages"][0]["envelope"]["payload"]["entity_revision"] = -1
        with self.assertRaises(ValidationError):
            s.deserialize_message(json.dumps(raw))

    def test_naive_time_rejected(self):
        with self.assertRaises(ValidationError):
            self.observation(observed_at=datetime(2026, 1, 1))

    def test_capacity_and_group_identity(self):
        with self.assertRaises(ValidationError):
            s.Shelter(shelter_id="s", position=dict(x=0, y=0), capacity=1, occupants=2)
        for changes in (dict(carried_civilians=2),
                        dict(carried_civilians=1, carried_group_ids=["g", "g"])):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                s.RescueTeamState(team_id="a", position=dict(x=0, y=0),
                                  neighbourhood_id="a", **changes)

    def test_resolution_requires_consistent_winner(self):
        with self.assertRaises(ValidationError):
            s.TaskClaimResolution(civilian_group_id="g", winning_claim_id=uuid4(),
                resolved_status="confirmed", resolution_reason="reconnect",
                resolved_at_tick=3, resolution_version=1)

    def test_ai_connectivity_and_context_roundtrip(self):
        status = s.AgentStatus(agent_id="a", neighbourhood_id="b", state="online",
            world_tick=1, radio_connected=False, decision_context_version=2)
        self.assertFalse(status.ai_available)
        request = s.AIRescueRequest(seed=42, decision_context_version=2,
            beliefs=s.TeamBeliefSnapshot(team_id="a", belief_version=3, world_tick=1))
        message = s.make_message(message_type=s.MessageType.AI_REQUEST,
            sender_id="a", sender_role=s.AgentRole.RESCUE_TEAM, payload=request)
        self.assertEqual(s.parse_payload(s.deserialize_message(s.serialize_message(message))), request)


if __name__ == "__main__":
    unittest.main()
