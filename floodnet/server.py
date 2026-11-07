"""FastAPI server wrapping the floodnet.sim Python simulation for the frontend."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Literal
from threading import RLock
from contextlib import asynccontextmanager

from floodnet.sim.drone_agents import DroneAgentSystem

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from floodnet.sim.pathing import tup
from floodnet.sim.runner import build_simple_agents
from floodnet.sim.scenario import load_scenario
from floodnet.sim.world import World
from schema import ActionStatus, CivilianStatus


# Own the in-memory dashboard simulation and serialize its agent-to-world integration.
class SimManager:
    # Keep the configured provider across resets so request accounting remains session-wide.
    def __init__(self, scenario_name: str = "small", drone_provider=None):
        self.drone_provider = drone_provider
        self.scenario_name = scenario_name
        self.reset(scenario_name)

    # Replace the world and all mission state; invalidate old workers before accepting new
    # actions.
    def reset(self, scenario_name: Optional[str] = None):
        if scenario_name:
            self.scenario_name = scenario_name
        if hasattr(self, "drone_ai"):
            self.drone_ai.close()
        self.cfg = load_scenario(self.scenario_name)
        self.world = World(self.cfg)
        self.agents = build_simple_agents(self.world)
        self.drone_ai = DroneAgentSystem(self.cfg, provider=self.drone_provider)
        self.drone_provider = self.drone_ai.provider
        self._event_sequence = 0
        self.drone_base = tup(self.cfg.drones[0].position)
        self.radio_connected: bool = True
        self.drone_status: str = "flying"
        self.drone_relayed_count: int = 0
        self.last_delivery_tick = None
        self.active_conflicts: int = 0
        self.resolved_conflicts: int = 0

        self.events: List[Dict[str, Any]] = [
            {
                "id": "ev_init_0",
                "tick": 0,
                "timestamp": self._format_tick(0),
                "category": "network",
                "severity": "info",
                "title": f"FloodNet Python Engine Started ({self.scenario_name})",
                "description": f"World initialized: {len(self.world.teams)} teams, {len(self.world.civilians)} civilian groups, shelter at ({self.world.shelter.position.x},{self.world.shelter.position.y})."
            }
        ]
        self.events.append(dict(id="ev_drone_ai_init", tick=0, timestamp=self._format_tick(0),
            category="ai", severity="info" if self.drone_ai.provider else "warning",
            title="Drone AI Status", description=self.drone_ai.reason))

    # Convert story ticks to the dashboard clock using the scenario tick duration.
    def _format_tick(self, tick: int) -> str:
        sec = tick * self.cfg.tick_seconds
        h = 9 + (sec // 3600)
        m = (sec % 3600) // 60
        s = sec % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    # Change communication availability without changing existing rescue orders.
    def set_radio(self, connected: bool):
        prev = self.radio_connected
        self.radio_connected = connected
        tick = self.world.tick
        ts = self._format_tick(tick)

        if prev != connected:
            if self.drone_status == "returning":
                self.drone_ai.return_home()
            else:
                self.drone_ai.invalidate()
            if connected:
                self.events.append({
                    "id": f"ev_radio_{tick}_{len(self.events)}",
                    "tick": tick,
                    "timestamp": ts,
                    "category": "network",
                    "severity": "success",
                    "title": "Radio Link Restored",
                    "description": "Tactical link between West and East areas re-established. Synchronizing team knowledge."
                })
            else:
                self.events.append({
                    "id": f"ev_radio_{tick}_{len(self.events)}",
                    "tick": tick,
                    "timestamp": ts,
                    "category": "network",
                    "severity": "danger",
                    "title": "NETWORK PARTITION: Radio Severed",
                    "description": "Teams in West and East operating independently on local beliefs. Relying on courier drone."
                })

    # Translate agent diagnostics into uniquely identified events for the existing frontend.
    def _drain_agent_events(self):
        for event in self.drone_ai.events:
            self._event_sequence += 1
            self.events.append(dict(event, id=f"ev_agent_{self._event_sequence}",
                timestamp=self._format_tick(event["tick"])))
        self.drone_ai.events.clear()

    # Sense, communicate, propose actions, validate the world transition, then publish dashboard
    # state.
    def step(self) -> Dict[str, Any]:
        cur_tick = self.world.tick
        ts = self._format_tick(cur_tick + 1)
        observations = self.world.observe_all()
        self.drone_ai.sense(self.world, self.agents, observations, self.radio_connected)
        drone = self.world.drones["drone-1"]
        # Deliver/reserve plans before teams decide, so a received order can be
        # acted upon in the same tick. Only the coordinator owns flight commands.
        proposals = [self.drone_ai.drone_action(self.world, self.agents, self.radio_connected)]
        proposals.extend(self.drone_ai.team_action(self.world, tid, self.agents[tid], radio=self.radio_connected)
                         for tid in sorted(self.world.teams))
        self._drain_agent_events()

        # 4. Step world
        outcome = self.world.step(proposals)
        self.drone_ai.apply_results(self.world, proposals, outcome)
        self.drone_relayed_count = self.drone_ai.delivered_count
        self.last_delivery_tick = self.drone_ai.last_delivery_tick
        if drone and not drone.enabled and self.drone_status == "returning":
            self.drone_status = "idle"

        # A stationary team can be overtaken by rising water. Report that
        # explicitly; its next decision seeks adjacent dry ground.
        for team_id, team in self.world.teams.items():
            if tup(team.position) in outcome.newly_flooded:
                self.events.append(dict(id=f"ev_team_flood_{cur_tick}_{team_id}",
                    tick=cur_tick + 1, timestamp=ts, category="team", severity="danger",
                    title=f"Rising Water Reached {team_id}",
                    description="Team position flooded while occupied. Seeking adjacent dry ground; will hold if surrounded."))
        for result in outcome.results:
            if (result.status == ActionStatus.REJECTED and result.team_id in self.world.teams
                    and result.message and ("flood" in result.message or "dry route" in result.message)):
                self.events.append(dict(id=f"ev_water_block_{cur_tick}_{result.team_id}",
                    tick=cur_tick + 1, timestamp=ts, category="team", severity="warning",
                    title=f"Unsafe Move Blocked: {result.team_id}", description=result.message))

        # 5. Process outcome into tactical events
        for u in outcome.status_updates:
            if u.status == CivilianStatus.PICKED_UP:
                group = self.world.civilians.get(u.civilian_group_id)
                size = group.size if group else 1
                self.events.append({
                    "id": f"ev_pickup_{cur_tick}_{u.civilian_group_id}",
                    "tick": cur_tick + 1,
                    "timestamp": ts,
                    "category": "rescue",
                    "severity": "success",
                    "title": f"Civilians Secured by {u.changed_by_team_id}",
                    "description": f"{u.changed_by_team_id} picked up {u.civilian_group_id} ({size} people). Heading to shelter."
                })
            elif u.status == CivilianStatus.DELIVERED:
                group = self.world.civilians.get(u.civilian_group_id)
                size = group.size if group else 1
                self.events.append({
                    "id": f"ev_drop_{cur_tick}_{u.civilian_group_id}",
                    "tick": cur_tick + 1,
                    "timestamp": ts,
                    "category": "rescue",
                    "severity": "success",
                    "title": f"Civilians Rescued by {u.changed_by_team_id}",
                    "description": f"{u.civilian_group_id} safely delivered to shelter. Occupants inside: {self.world.shelter.occupants}."
                })
            elif u.status == CivilianStatus.LOST:
                self.events.append({
                    "id": f"ev_lost_{cur_tick}_{u.civilian_group_id}",
                    "tick": cur_tick + 1,
                    "timestamp": ts,
                    "category": "conflict",
                    "severity": "danger",
                    "title": f"CIVILIAN CASUALTY: {u.civilian_group_id} Submerged",
                    "description": f"Flood water engulfed {u.civilian_group_id} before rescue units arrived."
                })

        self.active_conflicts = 0  # A single ownership ledger prevents duplicate assignments.

        # Keep event log capped at 70
        self.events = self.events[-70:]

        return self.get_state()

    def get_state(self) -> Dict[str, Any]:
        """Convert Python simulation state to the exact schema expected by frontend."""
        score = self.world.score()
        tick = self.world.tick
        ts = self._format_tick(tick)

        # 20x20 grid cells
        cells = []
        for y in range(self.world.height):
            row = []
            for x in range(self.world.width):
                pos = (x, y)
                is_flooded = pos in self.world.flooded
                is_river = x in (9, 10) and y < 12
                water_depth = 3 if is_river else (2 if is_flooded else 0)
                is_submerged_road = (y == 14 or x == 7 or x == 12) and is_flooded
                elevation = 1 if is_flooded else (5 if y >= 16 else 3)

                row.append({
                    "x": x,
                    "y": y,
                    "isFlooded": is_flooded,
                    "waterDepth": water_depth,
                    "isSubmergedRoad": is_submerged_road,
                    "elevation": elevation
                })
            cells.append(row)

        # Teams mapping
        team_alpha = self.world.teams.get("team-w1") or list(self.world.teams.values())[0]
        team_bravo = self.world.teams.get("team-e1") or list(self.world.teams.values())[-1]

        # Adapt authoritative positions and local orders to the unchanged team-panel contract.
        def format_team(t, callsign, color):
            return {
                "teamId": t.team_id,
                "name": f"Rescue Team {callsign} ({t.team_id})",
                "callsign": callsign,
                "color": color,
                "position": {"x": t.position.x, "y": t.position.y},
                "direction": "N",
                "state": ("waiting" if tup(t.position) in self.world.flooded else
                    "delivering" if t.carried_group_ids else
                    "moving" if self.drone_ai.orders[t.team_id] or (not self.radio_connected and t.team_id in self.drone_ai.wandering) else "idle"),
                "currentTargetId": self.world.shelter.shelter_id if t.carried_civilians else self.drone_ai.orders[t.team_id],
                "capacity": t.capacity,
                "carriedCivilians": t.carried_civilians,
                "carriedGroupIds": list(t.carried_group_ids),
                "neighbourhoodId": "neighbourhood_alpha" if t.neighbourhood_id == "west" else "neighbourhood_bravo",
                "plannedRoute": [{"x": x, "y": y} for x, y in self.drone_ai.routes[t.team_id]],
                "completedRoute": [{"x": x, "y": y} for x, y in self.drone_ai.history[t.team_id]],
                "lastCommTick": self.drone_ai.teams[t.team_id]["reported_tick"],
                "pendingOutgoingMessages": []
            }

        teams_dict = {
            "alpha": format_team(team_alpha, "Alpha", "#38bdf8"),
            "bravo": format_team(team_bravo, "Bravo", "#22c55e")
        }

        # Civilians mapping
        civilians_list = []
        for gid, c in sorted(self.world.civilians.items()):
            civilians_list.append({
                "groupId": c.group_id,
                "name": f"Civilians {c.group_id.replace('group-', '#')}",
                "position": {"x": c.position.x, "y": c.position.y},
                "size": c.size,
                "status": c.status.value,
                "pickedUpByTeamId": c.picked_up_by_team_id,
                "deliveredToShelterId": c.delivered_to_shelter_id
            })

        # Drone mapping
        drone_obj = self.world.drones.get("drone-1")
        drone_state = {
            "droneId": drone_obj.drone_id if drone_obj else "drone-1",
            "name": "AeroRelay Drone CR-1",
            "position": {"x": drone_obj.position.x, "y": drone_obj.position.y} if drone_obj else {"x": 10, "y": 17},
            "subPosition": {"x": drone_obj.position.x, "y": drone_obj.position.y} if drone_obj else {"x": 10, "y": 17},
            "status": self.drone_status,
            "enabled": drone_obj.enabled if drone_obj else True,
            "speed": self.cfg.drone_speed,
            "currentLegIndex": 0,
            "routeWaypoints": ([{"x": drone_obj.position.x, "y": drone_obj.position.y},
                {"x": self.drone_ai.flight_goal[0], "y": self.drone_ai.flight_goal[1]}]
                if drone_obj and self.drone_ai.flight_goal else []),
            "destinationNeighbourhood": ("neighbourhood_alpha" if
                (self.drone_ai.flight_goal[0] if self.drone_ai.flight_goal else drone_obj.position.x)
                < self.cfg.area_split_x else "neighbourhood_bravo"),
            "reasoning": self.drone_ai.reason,
            "aiModel": self.drone_ai.provider.model if self.drone_ai.provider else None,
            "agentSystem": self.drone_ai.state(),
            "carriedMessages": self.drone_ai.pending_messages(),
            "lastDeliveryTick": self.last_delivery_tick,
            "deliveryHistoryCount": self.drone_relayed_count
        }

        # Belief maps mapping
        # Render only this team's received knowledge, including original observation ticks.
        def format_belief(agent_id):
            agent = self.agents.get(agent_id)
            grid = {}
            known_civs = {}

            if agent:
                for pos in agent.known_flooded:
                    grid[f"{pos[0]},{pos[1]}"] = {
                        "x": pos[0],
                        "y": pos[1],
                        "state": "flooded",
                        "waterDepth": 2,
                        "observedAtTick": tick,
                        "observerId": agent_id
                    }
                # Safe ground near team
                t_pos = tup(self.world.teams[agent_id].position)
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        x, y = t_pos[0] + dx, t_pos[1] + dy
                        if 0 <= x < 20 and 0 <= y < 20 and (x, y) not in agent.known_flooded:
                            grid[f"{x},{y}"] = {
                                "x": x,
                                "y": y,
                                "state": "safe",
                                "observedAtTick": tick,
                                "observerId": agent_id
                            }

                for gid, (gpos, status, size) in agent.known_groups.items():
                    known_civs[gid] = {
                        "groupId": gid,
                        "position": {"x": gpos[0], "y": gpos[1]},
                        "size": size,
                        "status": status,
                        "observedTick": agent.known_group_versions.get(gid, (tick, 0))[0],
                        "observerId": agent_id
                    }

            return {
                "teamId": agent_id,
                "version": len(grid) + len(known_civs),
                "grid": grid,
                "knownCivilians": known_civs,
                "knownClaims": {},
                "lastUpdatedTick": tick
            }

        beliefs_dict = {
            "alpha": format_belief("team-w1"),
            "bravo": format_belief("team-e1")
        }

        # The existing panels now show actual assigned plans, not synthetic AI text.
        recommendations_dict = {
            "alpha": self.drone_ai.recommendation(team_alpha.team_id, team_alpha, tick),
            "bravo": self.drone_ai.recommendation(team_bravo.team_id, team_bravo, tick)
        }

        return {
            "tick": tick,
            "width": self.world.width,
            "height": self.world.height,
            "cells": cells,
            "neighbourhoods": {
                "alpha": {
                    "id": "neighbourhood_alpha",
                    "name": "West Sector (Alpha)",
                    "center": {"x": 5, "y": 10},
                    "radius": 6.0,
                    "bounds": {"minX": 0, "maxX": 9, "minY": 0, "maxY": 19},
                    "color": "#38bdf8"
                },
                "bravo": {
                    "id": "neighbourhood_bravo",
                    "name": "East Sector (Bravo)",
                    "center": {"x": 15, "y": 10},
                    "radius": 6.0,
                    "bounds": {"minX": 10, "maxX": 19, "minY": 0, "maxY": 19},
                    "color": "#22c55e"
                }
            },
            "radioConnected": self.radio_connected,
            "teams": teams_dict,
            "civilians": civilians_list,
            "shelter": {
                "shelterId": self.world.shelter.shelter_id,
                "name": "Northern Municipal Shelter",
                "position": {"x": self.world.shelter.position.x, "y": self.world.shelter.position.y},
                "capacity": self.world.shelter.capacity or 30,
                "occupants": self.world.shelter.occupants
            },
            "drone": drone_state,
            "beliefs": beliefs_dict,
            "recommendations": recommendations_dict,
            "events": self.events,
            "stats": {
                "totalCivilians": score["people_total"],
                "rescuedCivilians": score["people_rescued"],
                "awaitingRescue": score["people_total"] - score["people_rescued"] - score["people_lost"],
                "lostCivilians": score["people_lost"],
                "activeConflicts": self.active_conflicts,
                "resolvedConflicts": self.resolved_conflicts,
                "messagesRelayedByDrone": self.drone_relayed_count
            }
        }


# FastAPI Application instance
# Release the background agent executor when the development server shuts down.
@asynccontextmanager
async def lifespan(app):
    yield
    manager.drone_ai.close()


state_lock = RLock()
app = FastAPI(lifespan=lifespan, title="FloodNet Python Simulation Engine", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = SimManager(scenario_name="small")


# Read a consistent snapshot without advancing either agents or flood simulation.
@app.get("/api/state")
def get_state():
    with state_lock:
        return manager.get_state()


# Apply one authoritative tick while preventing concurrent requests from interleaving mutations.
@app.post("/api/step")
def step_sim():
    with state_lock:
        return manager.step()


# Validate the requested scenario name before rebuilding simulation state.
class ResetRequest(BaseModel):
    scenario: str = "small"


# Reject unsupported scenarios and return the newly initialized dashboard snapshot.
@app.post("/api/reset")
def reset_sim(req: ResetRequest):
    if req.scenario not in ("small", "default"):
        raise HTTPException(400, "Unknown scenario")
    with state_lock:
        manager.reset(req.scenario)
        return manager.get_state()


# Carry the operator's requested radio connectivity state.
class RadioRequest(BaseModel):
    connected: bool


# Apply the radio switch under the same lock used by simulation ticks.
@app.post("/api/radio")
def toggle_radio(req: RadioRequest):
    with state_lock:
        manager.set_radio(req.connected)
        return manager.get_state()


# Restrict operator commands to launch, pause, or return.
class DroneRequest(BaseModel):
    action: Literal["launch", "pause", "return"]


# Invalidate pending flight decisions and apply the operator command without rewriting team
# orders.
@app.post("/api/drone")
def control_drone(req: DroneRequest):
    with state_lock:
        drone = manager.world.drones.get("drone-1")
        if not drone:
            raise HTTPException(404, "Drone not found")
        manager.drone_ai.invalidate()
        if req.action == "launch":
            manager.drone_ai.launch()
            manager.drone_status = "flying"
            drone.enabled = True
        elif req.action == "pause":
            manager.drone_status = "paused"
            drone.enabled = False
        else:
            manager.drone_status = "returning"
            drone.enabled = True
            manager.drone_ai.return_home()
        return manager.get_state()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
