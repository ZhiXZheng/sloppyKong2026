from schema import *

observation = Observation(
    observer_id="team_1",
    entity=EntityReference(
        entity_type=EntityType.CIVILIAN_GROUP,
        entity_id="group_1"
    ),
    observed_at=utc_now(),
    observed_status="available"
)

message = make_message(
    message_type=MessageType.OBSERVATION,
    sender_id="team_1",
    sender_role=AgentRole.RESCUE_TEAM,
    payload=observation
)

# Serialise for transmission
encoded = serialize_message(message)

# Deserialize on the receiving agent
received = deserialize_message(encoded)

# Recover the validated payload
payload = parse_payload(received)
