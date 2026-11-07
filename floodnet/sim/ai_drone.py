"""Claude selects courier destinations; deterministic execution enforces flight limits."""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from person_b.ai_client import ClaudeProvider
from floodnet.sim.pathing import gp
from schema import ActionProposal, ActionType

HUBS = {"west": (5, 10), "east": (15, 10)}
SYSTEM = """You dispatch a flood-response courier drone. Choose west, east, or hold.
Use only the supplied local intelligence. Prioritize delivering carried packets to
 their destination, collecting updates during radio partitions, and visiting areas
whose information is oldest or never received. Avoid redundant trips while radio
is connected. Explain the operational reason briefly. Never invent observations."""


# Validate the older two-depot courier recommendation used by its standalone regression tests.
class DroneDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    destination: Literal["west", "east", "hold"]
    explanation: str = Field(min_length=1, max_length=600)


# Retain the original bounded courier adapter; dashboard scouting uses drone_agents.py.
class AIDrone:
    # Configure legacy courier limits and a single background HTTP worker.
    def __init__(self, provider=None, clock=time.monotonic, speed=2):
        self.speed = speed
        self.clock = clock
        self.provider = provider
        self.unavailable = False
        if provider is None:
            try:
                self.provider = ClaudeProvider(
                    model=os.environ.get("FLOODNET_CLAUDE_MODEL", "claude-haiku-5-5"),
                    max_tokens=192, max_requests=100)
            except ValueError:
                self.unavailable = True
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="drone-ai")
        self.pending = None
        self.goal = None
        self.destination = None
        self.reason = "Claude ready" if self.provider else "Claude unavailable: configure API_KEY"
        self.next_request = 0.0
        self.knowledge = {}
        self.freshness = {"west": None, "east": None}

    # Invalidate an in-flight result without allowing an unbounded request queue.
    def invalidate(self):
        # Retain an in-flight worker until it finishes: never queue unbounded work.
        if self.pending:
            self.pending["valid"] = False
        self.goal = None
        self.destination = None
        self.next_request = 0.0

    # Reject future decisions and release the legacy executor.
    def close(self):
        self.invalidate()
        self.pool.shutdown(wait=False, cancel_futures=True)

    # Override legacy waypoint selection with an operator-directed landing.
    def return_home(self):
        self.invalidate()
        self.goal = "base"
        self.destination = None
        self.reason = "Operator commanded return to launch base"

    # Validate the legacy structured response without exposing raw provider failures.
    def _generate(self, prompt):
        try:
            result = self.provider.generate(prompt, 3.0, DroneDecision.model_json_schema(), SYSTEM)
            decision = (DroneDecision.model_validate(result) if isinstance(result, dict)
                        else DroneDecision.model_validate_json(result))
            return decision, self.clock()
        except Exception:
            # Provider errors and credentials never enter the browser event stream.
            return None, self.clock()

    # Poll bounded planning work and execute validated fixed-depot courier movement.
    def decide(self, tick, drone, radio_connected, packets, base):
        now = self.clock()
        pos = (drone.position.x, drone.position.y)
        wait = lambda: ActionProposal(team_id=drone.drone_id, action_type=ActionType.WAIT,
                                      based_on_world_tick=tick, explanation=self.reason)
        if not drone.enabled:
            return wait()
        if self.pending:
            pending = self.pending
            if pending["future"].done():
                self.pending = None
                decision, finished = pending["future"].result()
                if pending["valid"] and finished < pending["deadline"] and decision:
                    self.reason = f"Claude: {decision.explanation}"
                    self.destination = None if decision.destination == "hold" else decision.destination
                    self.goal = self.destination
                    self.next_request = now + (5 if self.goal is None or HUBS[self.goal] == pos else 0)
                elif pending["valid"]:
                    self.reason = "Claude unavailable or invalid response; holding position"
                    self.next_request = now + 15
            elif now >= pending["deadline"] and pending["valid"]:
                pending["valid"] = False
                self.reason = "Claude timed out; holding position"
                self.next_request = now + 15
        if self.goal:
            target = base if self.goal == "base" else HUBS[self.goal]
            if pos != target:
                # Scenario speed is supplied by the server, never selected by AI.
                speed = self.speed
                dx = max(-speed, min(speed, target[0] - pos[0]))
                dy = max(-speed, min(speed, target[1] - pos[1]))
                return ActionProposal(team_id=drone.drone_id, action_type=ActionType.MOVE,
                    target_position=gp((pos[0] + dx, pos[1] + dy)),
                    based_on_world_tick=tick, explanation=self.reason)
            if self.goal == "base":
                self.reason = "Returned to launch base; awaiting launch"
                drone.enabled = False
                self.goal = None
                return wait()
            self.goal = None
        if self.provider and self.pending is None and now >= self.next_request:
            context = dict(tick=tick, position=pos, radio_connected=radio_connected,
                hubs=HUBS, area_freshness=self.freshness,
                carried_packets=[dict(origin=p["origin"], destination=p["destination"],
                                      created_tick=p["tick"]) for p in packets],
                last_received_knowledge=self.knowledge)
            self.pending = dict(future=self.pool.submit(self._generate, json.dumps(context)),
                                deadline=now + 3, valid=True)
            self.reason = "Awaiting Claude courier decision"
        return wait()
