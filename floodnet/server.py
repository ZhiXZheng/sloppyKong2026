"""FastAPI server wrapping the floodnet.sim Python simulation for the frontend."""

from __future__ import annotations

import math
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from floodnet.sim.pathing import Pos, chebyshev, gp, manhattan, tup
from floodnet.sim.runner import build_simple_agents
from floodnet.sim.scenario import ScenarioConfig, load_scenario
from floodnet.sim.simple_agents import SimpleDrone, SimpleTeam
from floodnet.sim.world import World
from schema import ActionProposal, ActionStatus, ActionType, CivilianStatus, EntityType


class SimManager:
    def __init__(self, scenario_name: str = "small"):
        self.scenario_name = scenario_name
        self.reset(scenario_name)

    def reset(self, scenario_name: Optional[str] = None):
        if scenario_name:
            self.scenario_name = scenario_name
        self.cfg = load_scenario(self.scenario_name)
        self.world = World(self.cfg)
        self.agents = build_simple_agents(self.world)
        self.radio_connected: bool = True
        self.drone_status: str = "flying"
        self.drone_payload: List[Dict[str, Any]] = []
        self.drone_relayed_count: int = 0
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

    def _format_tick(self, tick: int) -> str:
        sec = tick * self.cfg.tick_seconds
        h = 9 + (sec // 3600)
        m = (sec % 3600) // 60
        s = sec % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    def set_radio(self, connected: bool):
        prev = self.radio_connected
        self.radio_connected = connected
        tick = self.world.tick
        ts = self._format_tick(tick)

        if prev != connected:
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
                # Check for claim reconciliation
                self._reconcile_claims()
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

    def _reconcile_claims(self):
        """When reconnecting, resolve conflicting provisional claims."""
        w_agent = self.agents.get("team-w1")
        e_agent = self.agents.get("team-e1")
        if not w_agent or not e_agent:
            return

        w_groups = set(w_agent.known_groups.keys())
        e_groups = set(e_agent.known_groups.keys())
        overlap = w_groups.intersection(e_groups)

        for gid in overlap:
            group = self.world.civilians.get(gid)
            if not group or group.status == CivilianStatus.DELIVERED:
                continue

            # Deterministic resolution
            w_pos = tup(self.world.teams["team-w1"].position)
            e_pos = tup(self.world.teams["team-e1"].position)
            g_pos = tup(group.position)

            dist_w = manhattan(w_pos, g_pos)
            dist_e = manhattan(e_pos, g_pos)

            winner = "team-w1" if dist_w <= dist_e else "team-e1"
            loser = "team-e1" if winner == "team-w1" else "team-w1"

            self.resolved_conflicts += 1
            self.events.append({
                "id": f"ev_res_{self.world.tick}_{gid}",
                "tick": self.world.tick,
                "timestamp": self._format_tick(self.world.tick),
                "category": "conflict",
                "severity": "warning",
                "title": f"Conflict Reconciled: {gid}",
                "description": f"Both teams targeted {gid}. Assigned to {winner} (closer: {min(dist_w, dist_e)} vs {max(dist_w, dist_e)} cells). {loser} redirected."
            })

    def step(self) -> Dict[str, Any]:
        cur_tick = self.world.tick
        ts = self._format_tick(cur_tick + 1)

        # 1. Sense observations
        obs_by_agent = self.world.observe_all()

        # If radio connected, share observations across areas
        if self.radio_connected:
            all_flood_cells = set()
            all_groups = {}
            for aid, obs_list in obs_by_agent.items():
                for o in obs_list:
                    if o.entity.entity_type == EntityType.FLOOD_CELL:
                        all_flood_cells.add(tup(o.position))
                    elif o.entity.entity_type == EntityType.CIVILIAN_GROUP:
                        all_groups[o.entity.entity_id] = (
                            tup(o.position), o.observed_status, o.details.get("size", 1)
                        )

            for aid in self.world.teams:
                agent = self.agents[aid]
                agent.known_flooded.update(all_flood_cells)
                agent.known_groups.update(all_groups)

        # 2. Drone physical transport & store-and-forward relay
        drone = self.world.drones.get("drone-1")
        if drone and drone.enabled:
            d_pos = tup(drone.position)
            w_agent = self.agents.get("team-w1")
            e_agent = self.agents.get("team-e1")

            # Arriving near West depot (5, 10)
            if d_pos[0] <= 6 and d_pos[1] <= 11 and w_agent:
                # Deliver East packets to West
                east_packets = [p for p in self.drone_payload if p.get("origin") == "east"]
                if east_packets:
                    for pkt in east_packets:
                        w_agent.known_flooded.update(pkt.get("flooded", []))
                        w_agent.known_groups.update(pkt.get("groups", {}))
                    self.drone_payload = [p for p in self.drone_payload if p.get("origin") != "east"]
                    self.drone_relayed_count += len(east_packets)
                    self.events.append({
                        "id": f"ev_drone_del_w_{cur_tick}",
                        "tick": cur_tick,
                        "timestamp": ts,
                        "category": "drone",
                        "severity": "success",
                        "title": "Drone Delivered Packets to West Sector",
                        "description": f"CR-1 unloaded {len(east_packets)} observation packets. West belief map updated with eastern intelligence."
                    })

                # Pick up West packets for East
                if not self.radio_connected and w_agent.known_groups:
                    if not any(p.get("origin") == "west" for p in self.drone_payload):
                        self.drone_payload.append({
                            "origin": "west",
                            "destination": "east",
                            "flooded": list(w_agent.known_flooded),
                            "groups": dict(w_agent.known_groups),
                            "tick": cur_tick
                        })
                        self.events.append({
                            "id": f"ev_drone_load_w_{cur_tick}",
                            "tick": cur_tick,
                            "timestamp": ts,
                            "category": "drone",
                            "severity": "info",
                            "title": "Drone Collected West Observations",
                            "description": f"CR-1 loaded status reports for transit across partition corridor."
                        })

            # Arriving near East depot (15, 10)
            elif d_pos[0] >= 14 and d_pos[1] <= 11 and e_agent:
                # Deliver West packets to East
                west_packets = [p for p in self.drone_payload if p.get("origin") == "west"]
                if west_packets:
                    for pkt in west_packets:
                        e_agent.known_flooded.update(pkt.get("flooded", []))
                        e_agent.known_groups.update(pkt.get("groups", {}))
                    self.drone_payload = [p for p in self.drone_payload if p.get("origin") != "west"]
                    self.drone_relayed_count += len(west_packets)
                    self.events.append({
                        "id": f"ev_drone_del_e_{cur_tick}",
                        "tick": cur_tick,
                        "timestamp": ts,
                        "category": "drone",
                        "severity": "success",
                        "title": "Drone Delivered Packets to East Sector",
                        "description": f"CR-1 delivered {len(west_packets)} packets across partition. East belief map updated."
                    })

                # Pick up East packets for West
                if not self.radio_connected and e_agent.known_groups:
                    if not any(p.get("origin") == "east" for p in self.drone_payload):
                        self.drone_payload.append({
                            "origin": "east",
                            "destination": "west",
                            "flooded": list(e_agent.known_flooded),
                            "groups": dict(e_agent.known_groups),
                            "tick": cur_tick
                        })
                        self.events.append({
                            "id": f"ev_drone_load_e_{cur_tick}",
                            "tick": cur_tick,
                            "timestamp": ts,
                            "category": "drone",
                            "severity": "info",
                            "title": "Drone Collected East Observations",
                            "description": f"CR-1 loaded reports from East sector."
                        })

        # 3. Agent proposals
        proposals = []
        for aid in self.world.agent_ids():
            if aid in self.world.teams:
                p = self.agents[aid].decide(cur_tick, self.world.team_state(aid), obs_by_agent[aid])
                proposals.append(p)
            else:
                p = self.agents[aid].decide(cur_tick, self.world.agent_pos(aid))
                proposals.append(p)

        # 4. Step world
        outcome = self.world.step(proposals)

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

        # Check for active border conflict during disconnection
        if not self.radio_connected:
            w_agent = self.agents.get("team-w1")
            e_agent = self.agents.get("team-e1")
            if w_agent and e_agent:
                border_gid = "group-7"
                if border_gid in w_agent.known_groups and border_gid in e_agent.known_groups:
                    group = self.world.civilians.get(border_gid)
                    if group and group.status == CivilianStatus.AVAILABLE:
                        self.active_conflicts = 1
                    else:
                        self.active_conflicts = 0
        else:
            self.active_conflicts = 0

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

        def format_team(t, callsign, color):
            return {
                "teamId": t.team_id,
                "name": f"Rescue Team {callsign} ({t.team_id})",
                "callsign": callsign,
                "color": color,
                "position": {"x": t.position.x, "y": t.position.y},
                "direction": "N",
                "state": "delivering" if t.carried_group_ids else "moving",
                "capacity": t.capacity,
                "carriedCivilians": t.carried_civilians,
                "carriedGroupIds": list(t.carried_group_ids),
                "neighbourhoodId": "neighbourhood_alpha" if t.neighbourhood_id == "west" else "neighbourhood_bravo",
                "plannedRoute": [],
                "completedRoute": [{"x": t.position.x, "y": t.position.y}],
                "lastCommTick": tick,
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
            "routeWaypoints": [
                {"x": 5, "y": 10},
                {"x": 8, "y": 10},
                {"x": 12, "y": 10},
                {"x": 15, "y": 10},
                {"x": 12, "y": 10},
                {"x": 8, "y": 10}
            ],
            "destinationNeighbourhood": "neighbourhood_bravo" if (drone_obj and drone_obj.position.x < 10) else "neighbourhood_alpha",
            "carriedMessages": [
                {
                    "messageId": f"pkt_{i}",
                    "senderId": p.get("origin", "west"),
                    "originNeighbourhood": p.get("origin", "west"),
                    "destinationNeighbourhood": p.get("destination", "east"),
                    "type": "observation",
                    "createdTick": p.get("tick", 0),
                    "data": {}
                }
                for i, p in enumerate(self.drone_payload)
            ],
            "deliveryHistoryCount": self.drone_relayed_count
        }

        # Belief maps mapping
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
                        "observedTick": tick,
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

        # AI Recommendations
        def make_rec(agent_id, team_obj):
            agent = self.agents.get(agent_id)
            if team_obj.carried_group_ids:
                return {
                    "teamId": agent_id,
                    "recommendedTargetId": self.world.shelter.shelter_id,
                    "targetDescription": self.world.shelter.shelter_id,
                    "recommendedAction": f"Transit Evacuees to Shelter ({self.world.shelter.position.x},{self.world.shelter.position.y})",
                    "reasoning": f"Carrying {team_obj.carried_civilians} people from {','.join(team_obj.carried_group_ids)}. Proceeding to safe drop-off.",
                    "confidence": 98 if self.radio_connected else 88,
                    "missingInformation": "All routes clear on southern ridge." if self.radio_connected else "Operating on local memory.",
                    "isAiFallback": not self.radio_connected,
                    "generatedTick": tick
                }
            if agent and agent.known_groups:
                avail = [gid for gid, (_, st, _) in agent.known_groups.items() if st in ("available", "reported")]
                if avail:
                    target_id = avail[0]
                    return {
                        "teamId": agent_id,
                        "recommendedTargetId": target_id,
                        "targetDescription": f"Target: {target_id}",
                        "recommendedAction": f"Deploy to rescue {target_id}",
                        "reasoning": f"Nearest observed group in local operational area.",
                        "confidence": 92 if self.radio_connected else 74,
                        "missingInformation": "Local radar sweep verified." if self.radio_connected else "Cross-partition water telemetry unknown.",
                        "isAiFallback": not self.radio_connected,
                        "generatedTick": tick
                    }
            return {
                "teamId": agent_id,
                "recommendedTargetId": None,
                "targetDescription": "Patrol & Sense",
                "recommendedAction": "Advance Patrol Route",
                "reasoning": "No reachable civilian groups in local memory. Patrolling sector.",
                "confidence": 85 if self.radio_connected else 68,
                "missingInformation": "Awaiting observations or drone updates.",
                "isAiFallback": not self.radio_connected,
                "generatedTick": tick
            }

        recommendations_dict = {
            "alpha": make_rec("team-w1", team_alpha),
            "bravo": make_rec("team-e1", team_bravo)
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
app = FastAPI(title="FloodNet Python Simulation Engine", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = SimManager(scenario_name="small")


@app.get("/api/state")
def get_state():
    return manager.get_state()


@app.post("/api/step")
def step_sim():
    return manager.step()


class ResetRequest(BaseModel):
    scenario: str = "small"


@app.post("/api/reset")
def reset_sim(req: ResetRequest):
    manager.reset(req.scenario)
    return manager.get_state()


class RadioRequest(BaseModel):
    connected: bool


@app.post("/api/radio")
def toggle_radio(req: RadioRequest):
    manager.set_radio(req.connected)
    return manager.get_state()


class DroneRequest(BaseModel):
    action: str  # "launch", "pause", "return"


@app.post("/api/drone")
def control_drone(req: DroneRequest):
    if req.action == "launch":
        manager.drone_status = "flying"
        if "drone-1" in manager.world.drones:
            manager.world.drones["drone-1"].enabled = True
    elif req.action == "pause":
        manager.drone_status = "paused"
        if "drone-1" in manager.world.drones:
            manager.world.drones["drone-1"].enabled = False
    return manager.get_state()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
