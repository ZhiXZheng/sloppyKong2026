"""Readable terminal output for the offline demo; no optional dependencies."""

import json
import textwrap


# Format optional protocol positions for human-readable terminal events.
def position(value):
    return f"({value['x']}, {value['y']})" if value else "unknown"


# Turn recorded protocol/action events into readable operational explanations.
def event_text(event):
    kind = event["type"]
    team = f"Team {event['team'].upper()}" if event.get("team") else "Network"
    if kind in ("initial_observation", "local_observation"):
        observation = event["observation"]
        source = "Initial report" if kind == "initial_observation" else "Observed"
        return f"{team} | {source}: {observation['entity']['entity_id']} at {position(observation['position'])}" + (
            f" [{observation['observed_status']}]" if observation.get("observed_status") else "")
    if kind == "connectivity":
        return f"Radio  | Link {'UP' if event['radio_connected'] else 'DOWN'}; AI OFF (rules-only demo)"
    if kind == "courier_delivery":
        observation = event["observation"]
        return (f"Drone  | Delivered {event['observations']} observation to {team}: "
                f"{observation['entity']['entity_id']} at {position(observation['position'])}; "
                f"{event['duplicate_deliveries_ignored']} duplicate ignored")
    if kind == "drone_movement":
        return (f"Drone  | FLY {position(event['position_before'])} -> "
                f"{position(event['position_after'])}; {event['phase']}")
    if kind == "message":
        payload = event["payload"]
        if event["message_type"] == "rescue.task_claim":
            return f"{team} | Claim {payload['civilian_group_id']}: {payload['status'].upper()} (v{payload['claim_version']})"
        if event["message_type"] == "world.observation":
            return f"{team} | Queued observation for radio/courier: {payload['entity']['entity_id']}"
        return f"{team} | Message: {event['message_type']}"
    if kind == "action":
        action = event["action"]
        name = action["action_type"].upper().replace("_", " ")
        target = f" -> {position(action['target_position'])}" if action.get("target_position") else ""
        entity = f" [{action['target_entity_id']}]" if action.get("target_entity_id") else ""
        return f"{team} | {name}{target}{entity}\n         Reason: {action['explanation']}"
    if kind == "action_result":
        line = f"{team} | Result: {event['result']['status'].upper()}"
        if "position_after" in event:
            line += f" | {position(event['position_before'])} -> {position(event['position_after'])}"
            groups = ", ".join(event["carried_group_ids"]) or "none"
            line += f" | Carrying: {event['carried_civilians']} people (groups: {groups})"
        return line
    if kind == "civilian_status":
        return f"{team} | Civilian group {event['group_id']}: {event['status'].upper().replace('_', ' ')}"
    if kind == "claim_resolution":
        resolution = event["resolution"]
        winner = resolution["winning_team_id"]
        return (f"Claims | {resolution['civilian_group_id']}: winner "
                f"{('Team ' + winner.upper()) if winner else 'none'}; {resolution['resolution_reason']}")
    if kind == "target":
        return f"{team} | Current target: {event['target'] or 'none'}"
    return json.dumps(event)


# Print one comparison tick while wrapping long AI reasons to terminal width.
def print_tick(record):
    scenario = (f"Drone {'ON' if record['drone_on'] else 'OFF'} | Seed {record['seed']}"
                if record["scenario"] == "comparison" else "Border conflict")
    link = "UP" if record["radio_connected"] else "DOWN"
    print(f"\n--- Tick {record['tick']:02d} | {scenario} | Radio {link} ---")
    for event in record["events"]:
        # Keep long reasons readable in narrow PowerShell terminals.
        for line in event_text(event).splitlines():
            print(textwrap.fill(line, width=100, subsequent_indent="           ",
                                replace_whitespace=False, drop_whitespace=True))
    if "rescued" in record:
        print(f"  Rescued: {record['rescued']}/{record['total']}")
    print(flush=True)


# Show the final people-rescued comparison for a single deterministic run.
def print_summary(result):
    print(f"\n{'=' * 64}\n"
          f"FINAL | Drone {'ON' if result['drone_on'] else 'OFF'} | Seed {result['seed']} | "
          f"Rescued {result['rescued']}/{result['total']}\n{'=' * 64}", flush=True)


# Display both teams' final border-task choices after reconnection.
def print_border_summary(targets):
    print("\nBorder targets after reconnect:")
    for team, target in sorted(targets.items()):
        print(f"  Team {team.upper()}: {target or 'no target'}")
