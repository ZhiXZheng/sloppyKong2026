"""Offline A/C stand-ins for integration contracts, not the production simulation."""

import argparse
from copy import deepcopy
import json

from schema import (
    ActionResult, ActionStatus, ActionType, AgentRole, CivilianGroup,
    CivilianStatus, ClaimStatus, CourierPacket, DroneState, EntityReference, EntityType,
    MessageEnvelope, MessageType, Observation, RelayedMessage, RescueTeamState,
    TaskClaimResolution,
)
from .controller import AISettings, RescueController
from .runtime import Runtime


def courier_state(tick, enabled):
    """Scripted fixture flight: depart tick 2, reach the shelter relay tick 9."""
    progress = max(0, min(8, tick - 1)) if enabled else 0
    return DroneState(drone_id="courier", enabled=enabled,
        position={"x": 4 - min(progress, 4), "y": 4 - max(0, progress - 4)},
        destination_neighbourhood="east" if enabled and 2 <= tick < 9 else None,
        world_tick=max(0, tick))


def decision_events(decision):
    """Include both agents' decisions and every outbound protocol message."""
    return [dict(type="message", team=envelope.sender_id,
                 message_type=envelope.message_type.value, world_tick=envelope.world_tick,
                 payload=deepcopy(envelope.payload)) for envelope in decision.outbound] + [
        dict(type="action", team=decision.action.team_id,
             action=decision.action.model_dump(mode="json"))]


def run_comparison(drone_on=True, seed=42, ticks=30, on_tick=None):
    runtime = Runtime(f"demo/{seed}")
    controllers = {team: RescueController(team, seed=seed, settings=AISettings(False))
                   for team in ("a", "b")}
    states = {team: RescueTeamState(team_id=team, position={"x": x, "y": 0},
              capacity=1, neighbourhood_id=area) for team, x, area in (("a", 0, "west"), ("b", 6, "east"))}
    groups = {name: CivilianGroup(group_id=name, position={"x": x, "y": y}, size=1,
                                  last_updated_at=runtime.timestamp(0))
              for name, x, y in (("west", 1, 0), ("border", 3, 0), ("hidden", 7, 1))}
    revisions = {group: 0 for group in groups}
    actions, events, tick_events, initial_events = [], [], [], []

    def world_view(tick):
        return dict(width=20, height=20,
            rescue_teams=[states[team].model_dump(mode="json") for team in sorted(states)],
            civilian_groups=[groups[group].model_dump(mode="json") for group in sorted(groups)],
            shelters=[dict(shelter_id="shelter", position=dict(x=0, y=0))],
            flood_cells=[], drone=courier_state(tick, drone_on).model_dump(mode="json"))

    initial_world = world_view(-1)

    def observe(group_id, tick, observer):
        group = groups[group_id]
        return Observation(observation_id=runtime.new_id("observation"), observer_id=observer,
            entity=EntityReference(entity_type=EntityType.CIVILIAN_GROUP, entity_id=group_id),
            position=group.position, observed_status=group.status.value,
            observed_tick=tick, entity_revision=revisions[group_id], observed_at=runtime.timestamp(tick),
            details={"size": group.size, "picked_up_by_team_id": group.picked_up_by_team_id,
                     "delivered_to_shelter_id": group.delivered_to_shelter_id})

    for team, group in (("a", "west"), ("b", "border")):
        initial = [observe(group, 0, f"initial-report-{team}"),
            Observation(observation_id=runtime.new_id("shelter"), observer_id="initial-map",
                entity=EntityReference(entity_type=EntityType.SHELTER, entity_id="shelter"),
                position={"x": 0, "y": 0}, observed_tick=0, entity_revision=0,
                observed_at=runtime.timestamp(0), details={"capacity": None, "occupants": 0})]
        controllers[team].observe(initial)
        initial_events.extend(dict(type="initial_observation", team=team,
                                   observation=o.model_dump(mode="json")) for o in initial)

    # A remote observer's report can reach this isolated team only by courier.
    report = MessageEnvelope(message_id=runtime.new_id("message"), event_id=runtime.new_id("event"),
        message_type=MessageType.OBSERVATION, sender_id="remote-observer",
        sender_role=AgentRole.RESCUE_TEAM, created_at=runtime.timestamp(1),
        payload=observe("hidden", 1, "remote-observer").model_dump(mode="json"))
    for tick in range(ticks):
        current_events = initial_events if tick == 0 else []
        connected = not (2 <= tick < 10)
        if tick in (0, 2, 10):
            current_events.append(dict(type="connectivity", radio_connected=connected,
                                       ai_enabled=False))
        if drone_on and 2 <= tick <= 9:
            drone = courier_state(tick, True)
            current_events.append(dict(type="drone_movement", drone_id=drone.drone_id,
                position_before=courier_state(tick - 1, True).position.model_dump(),
                position_after=drone.position.model_dump(),
                phase="arrived at relay" if tick == 9 else "carrying observation to relay"))
        if drone_on and tick == 9:
            packet = CourierPacket(packet_id=runtime.new_id("packet"), drone_id="courier",
                source_neighbourhood="west", destination_neighbourhood="east",
                departed_at=runtime.timestamp(2), delivered_at=runtime.timestamp(9),
                messages=[RelayedMessage(envelope=report, original_sender_id="remote-observer",
                                         picked_up_at=runtime.timestamp(2))])
            envelope = MessageEnvelope(message_id=runtime.new_id("courier-message"),
                event_id=runtime.new_id("courier-event"), message_type=MessageType.COURIER_PACKET,
                sender_id="courier", sender_role=AgentRole.COURIER_DRONE, recipient_id="b",
                created_at=runtime.timestamp(tick), payload=packet.model_dump(mode="json"))
            controllers["b"].receive([envelope, envelope])
            events.append("tick 9: courier delivered one observation (duplicate delivery ignored)")
            current_events.append(dict(type="courier_delivery", team="b", observations=1,
                duplicate_deliveries_ignored=1, observation=deepcopy(report.payload)))
        for team in sorted(controllers):
            controller, state = controllers[team], states[team]
            for group_id, group in groups.items():
                if abs(group.position.x - state.position.x) + abs(group.position.y - state.position.y) <= 1:
                    local = observe(group_id, tick, team)
                    controller.observe([local])
                    current_events.append(dict(type="local_observation", team=team,
                                               observation=local.model_dump(mode="json")))
            decision = controller.step(state, connected, tick, float(tick))
            current_events.extend(decision_events(decision))
            action = decision.action
            actions.append(action.model_dump(mode="json"))
            data = state.model_dump()
            status = ActionStatus.COMPLETED
            if action.action_type == ActionType.MOVE:
                pos = action.target_position
                if abs(pos.x - state.position.x) + abs(pos.y - state.position.y) == 1:
                    data["position"] = pos
                else:
                    status = ActionStatus.REJECTED
            elif action.action_type == ActionType.PICKUP:
                group = groups.get(action.target_entity_id)
                if (group and group.status == CivilianStatus.AVAILABLE and group.position == state.position
                        and state.carried_civilians + group.size <= state.capacity):
                    data.update(carried_civilians=group.size, carried_group_ids=[group.group_id])
                    groups[group.group_id] = group.model_copy(update={
                        "status": CivilianStatus.PICKED_UP, "picked_up_by_team_id": team,
                        "last_updated_at": runtime.timestamp(tick)})
                    revisions[group.group_id] += 1
                else:
                    status = ActionStatus.REJECTED
            elif action.action_type == ActionType.DROP_OFF:
                if state.position.x == state.position.y == 0 and state.carried_civilians:
                    for group_id in state.carried_group_ids:
                        groups[group_id] = groups[group_id].model_copy(update={
                            "status": CivilianStatus.DELIVERED, "delivered_to_shelter_id": "shelter",
                            "last_updated_at": runtime.timestamp(tick)})
                        revisions[group_id] += 1
                    data.update(carried_civilians=0, carried_group_ids=[])
                else:
                    status = ActionStatus.REJECTED
            states[team] = RescueTeamState.model_validate(data)
            result = ActionResult(action_id=action.action_id, team_id=team,
                status=status, applied_at_tick=tick, affected_entity_id=action.target_entity_id,
                resulting_position=states[team].position)
            controller.apply_result(result)
            current_events.append(dict(type="action_result", team=team,
                result=result.model_dump(mode="json"),
                position_before=state.position.model_dump(),
                position_after=states[team].position.model_dump(),
                carried_group_ids=list(states[team].carried_group_ids),
                carried_civilians=states[team].carried_civilians))
            if status == ActionStatus.COMPLETED and action.action_type in (ActionType.PICKUP, ActionType.DROP_OFF):
                affected = ([action.target_entity_id] if action.action_type == ActionType.PICKUP
                            else state.carried_group_ids)
                current_events.extend(dict(type="civilian_status", team=team,
                    group_id=group_id, status=groups[group_id].status.value)
                    for group_id in affected)
        record = dict(type="tick", scenario="comparison", seed=seed, drone_on=drone_on,
            tick=tick, radio_connected=connected, events=current_events,
            world=world_view(tick),
            team_views={team: dict(target=controllers[team].target, reason=controllers[team].reason,
                known_group_ids=[o.entity.entity_id for o in controllers[team].beliefs.observations(EntityType.CIVILIAN_GROUP)])
                for team in sorted(controllers)},
            rescued=sum(g.size for g in groups.values() if g.status == CivilianStatus.DELIVERED),
            total=sum(g.size for g in groups.values()))
        tick_events.append(record)
        if on_tick is not None:
            on_tick(deepcopy(record))
    return dict(seed=seed, drone_on=drone_on, rescued=sum(g.size for g in groups.values()
                if g.status == CivilianStatus.DELIVERED), total=sum(g.size for g in groups.values()),
                events=events, actions=actions, tick_events=tick_events, initial_world=initial_world)


def border_conflict(on_tick=None):
    """Exercise resolution delivery, with Person A's arbiter represented explicitly."""
    runtime = Runtime("border-fixture")
    controllers = [RescueController(team, settings=AISettings(False)) for team in ("a", "b")]
    claims, first_events, reconnect_events = [], [], []
    for controller in controllers:
        controller.observe([Observation(observation_id=runtime.new_id("observation"), observer_id=controller.team_id,
            entity=EntityReference(entity_type=EntityType.CIVILIAN_GROUP, entity_id="border"),
            position={"x": 3, "y": 0}, observed_status="available", details={"size": 1},
            observed_tick=0, entity_revision=0, observed_at=runtime.timestamp(0))])
        state = RescueTeamState(team_id=controller.team_id, position={"x": 2, "y": 0},
                                neighbourhood_id=controller.team_id)
        decision = controller.step(state, False, 0, 0)
        first_events.extend(decision_events(decision))
        claims.extend([envelope for envelope in decision.outbound if envelope.message_type == MessageType.TASK_CLAIM])
        result = ActionResult(action_id=decision.action.action_id, team_id=controller.team_id,
                              status="completed", applied_at_tick=0)
        controller.apply_result(result)
        first_events.append(dict(type="action_result", team=controller.team_id,
                                 result=result.model_dump(mode="json")))
    if on_tick is not None:
        on_tick(dict(type="tick", scenario="border_conflict", tick=0,
                     radio_connected=False, events=first_events))
    from .beliefs import claim_order
    from schema import parse_payload
    ordered = sorted([parse_payload(c) for c in claims], key=claim_order)
    resolution = TaskClaimResolution(civilian_group_id="border", winning_team_id=ordered[0].team_id,
        winning_claim_id=ordered[0].claim_id, resolved_status=ClaimStatus.CONFIRMED,
        conflicting_claim_ids=[c.claim_id for c in ordered], resolution_reason="Reconnect; deterministic claim order",
        resolved_at_tick=1, resolution_version=1, resolved_at=runtime.timestamp(1))
    envelope = MessageEnvelope(message_type=MessageType.TASK_CLAIM_RESOLUTION,
        sender_id="simulation", sender_role=AgentRole.SIMULATION,
        payload=resolution.model_dump(mode="json"))
    reconnect_events.append(dict(type="claim_resolution", resolution=resolution.model_dump(mode="json")))
    for controller in controllers:
        controller.receive(claims + [envelope])
        state = RescueTeamState(team_id=controller.team_id, position={"x": 3, "y": 0},
                                neighbourhood_id=controller.team_id)
        decision = controller.step(state, True, 1, 1)
        reconnect_events.extend(decision_events(decision))
        reconnect_events.append(dict(type="target", team=controller.team_id, target=controller.target))
    if on_tick is not None:
        on_tick(dict(type="tick", scenario="border_conflict", tick=1,
                     radio_connected=True, events=reconnect_events))
    return {controller.team_id: controller.target for controller in controllers}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--ticks", type=int, default=30)
    parser.add_argument("--summary-only", action="store_true", help="Hide per-tick events")
    parser.add_argument("--json", action="store_true", help="Print full JSON records instead of readable text")
    parser.add_argument("--visual", action="store_true", help="Open an animated grid replay in your browser")
    parser.add_argument("--no-open", action="store_true", help="With --visual, save the replay without opening it")
    args = parser.parse_args()
    if args.ticks < 1:
        parser.error("--ticks must be positive")
    if args.visual:
        from .visualize import create_replay
        path = create_replay(seed=args.seed, ticks=args.ticks)
        print(f"Grid replay saved to: {path}")
        if not args.no_open:
            import webbrowser
            webbrowser.open(path.as_uri())
        return
    from .console import print_tick, print_summary, print_border_summary

    def print_json_tick(record):
        print(json.dumps(record), flush=True)

    callback = None if args.summary_only else (print_json_tick if args.json else print_tick)
    for enabled in (True, False):
        result = run_comparison(enabled, args.seed, args.ticks, on_tick=callback)
        result.pop("actions")
        result.pop("tick_events")
        result.pop("initial_world")
        if args.json:
            print(json.dumps(dict(type="summary", **result)), flush=True)
        else:
            print_summary(result)
    targets = border_conflict(on_tick=callback)
    if args.json:
        print(json.dumps(dict(type="border_summary", targets=targets)), flush=True)
    else:
        print_border_summary(targets)


if __name__ == "__main__":
    main()
