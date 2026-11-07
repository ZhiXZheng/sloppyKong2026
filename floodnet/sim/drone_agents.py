"""Three cooperating agents, one drone, and an authoritative rescue-task ledger.

The coordinator sees only drone observations and reports received over radio or
at physical contact. World truth is used solely for sensing, local team execution,
and the final simulation validation, never to feed unobserved facts to Claude.
"""
from __future__ import annotations

import json
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from person_b.ai_client import ClaudeAPIError, ClaudeProvider
from floodnet.sim.pathing import NEIGHBOURS, bfs_path, chebyshev, gp, manhattan, tup
from schema import ActionProposal, ActionStatus, ActionType, EntityType

AVAILABLE = {'available', 'reported', 'claimed', 'unknown'}
TERMINAL = {'delivered', 'lost'}
SCOUT_PROMPT = """You are the Scout agent of a flood-rescue drone system. Select exactly
one supplied search candidate ID. Search for undiscovered civilians, maximize new
sensor coverage, and inspect promising areas near known civilians and flood edges.
The drone flies over water. Avoid repeating covered areas. Only supplied evidence
is known; never invent civilian locations. The explanation MUST be at most 20 words."""
PLANNER_PROMPT = """You are the Rescue Planner agent of a flood-rescue drone system.
Rank ALL supplied civilian group IDs to maximize the number of people safely
returned to shelter. Consider group size, capacity, safe route lengths, and flood
proximity as an uncertain urgency indicator, not a known deadline. Infeasible
routes and courier delays matter. Do not choose teams: the coordinator assigns the
first eligible free team, or the closest eligible team if several are free. Busy
teams must finish their rescue AND deliver passengers before accepting another.
Use only reported evidence. Never invent groups, team availability, or deadlines.
Return unique IDs. The explanation MUST be at most 30 words; do not narrate individual route calculations."""


# Validate a model-selected search candidate before accepting it as a flight preference.
class ScoutDecision(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    candidate_id: str = Field(max_length=40)
    explanation: str = Field(min_length=1, max_length=500)


# Validate the model's ordered rescue queue and its explanatory confidence.
class RescueDecision(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    priorities: list[str] = Field(min_length=1, max_length=32)
    explanation: str = Field(min_length=1, max_length=600)
    confidence: float = Field(ge=0, le=1)

    # Reject duplicate IDs so one recommendation cannot allocate the same group twice.
    @field_validator('priorities')
    @classmethod
    def unique(cls, value):
        if len(value) != len(set(value)):
            raise ValueError('duplicate civilian groups')
        return value


# Transfer a validated reply or sanitized failure from a worker thread to the tick thread.
@dataclass
class WorkerResult:
    value: object
    finished: float
    error: str | None = None
    retryable: bool = True
    retry_after: float = 0.0
    latency: float = 0.0


class DecisionWorker:
    """Bounded background planning; execution never waits for a fresh response."""
    # Configure one bounded decision channel with an injectable clock for deterministic tests.
    def __init__(self, provider, pool, schema, prompt, clock, timeout=12.0):
        self.provider, self.pool, self.schema, self.prompt = provider, pool, schema, prompt
        self.clock, self.timeout = clock, timeout
        self.pending = None
        self.retry_after = 0.0
        self.disabled = False
        self.consecutive_failures = 0
        self.last_error = None
        self.last_latency = None
        self.stats = dict(requests=0, succeeded=0, failed=0, stale=0, rejected=0, categories={})
        self.status = 'Ready' if provider else 'Unavailable: configure API_KEY'

    # Mark outstanding results stale without queueing additional network work.
    def invalidate(self):
        if self.pending:
            self.pending['valid'] = False
        self.retry_after = 0.0

    # Perform HTTP and schema validation off-thread; return safe metadata instead of raw
    # exceptions.
    def _run(self, context):
        started = self.clock()
        try:
            raw = self.provider.generate(json.dumps(context), self.timeout,
                                         self.schema.model_json_schema(), self.prompt)
            value = (self.schema.model_validate(raw) if isinstance(raw, dict)
                     else self.schema.model_validate_json(raw))
            return WorkerResult(value, self.clock(), latency=self.clock()-started)
        except ClaudeAPIError as exc:
            return WorkerResult(None, self.clock(), exc.category, exc.retryable,
                                exc.retry_after, self.clock()-started)
        except ValidationError:
            return WorkerResult(None, self.clock(), 'invalid_reply', latency=self.clock()-started)
        except Exception:
            # Never expose arbitrary provider exception text (it may contain keys).
            return WorkerResult(None, self.clock(), 'provider_error', latency=self.clock()-started)

    # Dispatch only when there is no outstanding request, cooldown, or permanent service failure.
    def submit(self, context, metadata):
        if not self.provider or self.disabled or self.pending or self.clock() < self.retry_after:
            return False
        deadline = self.clock() + self.timeout
        self.pending = dict(future=self.pool.submit(self._run, context),
                            deadline=deadline, valid=True, metadata=metadata)
        self.stats['requests'] += 1
        self.status = 'Awaiting Claude; execution continuing'
        return True

    # Classify failure and schedule bounded exponential backoff, respecting provider retry hints.
    def _failure(self, category, retryable=True, retry_after=0.0):
        self.consecutive_failures += 1
        self.stats['failed'] += 1
        categories = self.stats['categories']
        categories[category] = categories.get(category, 0) + 1
        self.last_error = category
        self.disabled = not retryable
        delay = max(min(2 ** min(self.consecutive_failures, 5), 30), retry_after)
        self.retry_after = self.clock() + delay
        self.status = ('Claude timed out; execution continuing' if category == 'timeout' else
            f'Claude unavailable: {category}; ' + ('retry scheduled' if retryable else 'configuration required'))

    # Consume finished work without blocking; distinguish late, invalidated, and failed replies.
    def poll(self):
        p = self.pending
        if not p:
            return None
        if not p['future'].done():
            if p['valid'] and self.clock() >= p['deadline']:
                p['valid'], p['expired'] = False, True
                self._failure('timeout')
            return None
        self.pending = None
        result = p['future'].result()
        self.last_latency = result.latency
        if not p['valid']:
            if not p.get('expired'):
                self.stats['stale'] += 1
            return None
        if result.finished >= p['deadline']:
            self._failure('timeout')
            return None
        if result.error:
            self._failure(result.error, result.retryable, result.retry_after)
            return None
        self.stats['succeeded'] += 1
        self.consecutive_failures = 0
        self.last_error = None
        self.status = 'Claude decision received'
        return result.value, p['metadata']

    # Count an in-schema but semantically invalid choice as a rejected model decision.
    def reject(self):
        self.stats['rejected'] += 1
        self.stats['succeeded'] = max(0,self.stats['succeeded']-1)
        self._failure('invalid_choice')
        self.status = 'Claude reply rejected: unknown or invalid choices; execution continuing'

    # Expose counters and timing without including credentials, prompts, or provider response
    # bodies.
    def diagnostics(self):
        return dict(self.stats, lastError=self.last_error, lastLatencySeconds=self.last_latency,
                    retryInSeconds=round(max(0.0, self.retry_after-self.clock()), 2),
                    timeoutSeconds=self.timeout, disabled=self.disabled)


# Keep coordinator knowledge separate from the authoritative world and from each team's local
# memory.
class Evidence:
    # Start with no discovered civilians or flood cells; only received observations populate them.
    def __init__(self):
        self.groups = {}
        self.versions = {}
        self.flooded = set()

    # Preserve newer source versions when delayed courier reports arrive out of order.
    def merge(self, groups, versions, flooded=()):
        self.flooded.update(flooded)
        changed = []
        for gid, group in groups.items():
            version = tuple(versions.get(gid, (-1, -1)))
            if version >= self.versions.get(gid, (-1, -1)):
                if self.groups.get(gid) != group:
                    changed.append(gid)
                self.groups[gid] = group
                self.versions[gid] = version
        return changed

    # Extract civilian and flood facts from sensor observations without inventing unseen
    # information.
    def observe(self, observations):
        changed = []
        for o in observations:
            if o.entity.entity_type == EntityType.FLOOD_CELL:
                self.flooded.add(tup(o.position))
            elif o.entity.entity_type == EntityType.CIVILIAN_GROUP:
                gid = o.entity.entity_id
                changed += self.merge({gid: (tup(o.position), o.observed_status,
                                             o.details.get('size', 1))},
                                      {gid: (o.observed_tick, o.entity_revision)})
        return changed


def interaction_path(start, target, flooded, width, height):
    """Route to a dry cell at pickup/dropoff range; never allow a flooded goal."""
    if manhattan(start, target) <= 1 and start not in flooded:
        return []
    paths = []
    for dx, dy in ((0, 0), *NEIGHBOURS):
        goal = (target[0] + dx, target[1] + dy)
        if not (0 <= goal[0] < width and 0 <= goal[1] < height) or goal in flooded:
            continue
        path = bfs_path(start, goal, lambda p: p not in flooded, width, height)
        if path is not None:
            paths.append(path)
    return min(paths, key=lambda path: (len(path), path), default=None)


# Combine continuous coverage execution with prefetched Claude search preferences.
class ScoutAgent:
    # Track actual scanned cells separately from projected search destinations.
    def __init__(self, worker, width, height, radius, speed=2):
        self.worker = worker
        self.width, self.height, self.radius = width, height, radius
        self.speed = speed
        self.covered = set()
        self.goal = None
        self.preference = None
        self.reason = 'Preparing evidence-led search'
        self.decision_source = 'coverage_execution'

    # Return the clipped sensor footprint for a candidate or actual drone position.
    def footprint(self, pos):
        return {(x, y)
            for y in range(max(0, pos[1]-self.radius), min(self.height, pos[1]+self.radius+1))
            for x in range(max(0, pos[0]-self.radius), min(self.width, pos[0]+self.radius+1))}

    # Declare completion only when every cell was actually observed, including map edges.
    @property
    def complete(self):
        return len(self.covered) == self.width*self.height

    # Record real coverage and retire a waypoint only after the drone reaches it.
    def observe_position(self, pos):
        self.covered.update(self.footprint(pos))
        if self.goal == pos:
            self.goal = None

    # Rank useful unseen footprints; use exact unseen cells if the coarse waypoint grid leaves
    # gaps.
    def candidates(self, pos, evidence, covered=None):
        covered = self.covered if covered is None else covered
        choices = []
        locations = [(x, y) for y in range(2, self.height, 4) for x in range(2, self.width, 4)]
        # Edge/small-grid completion: every unseen cell is reachable by the drone.
        # This prevents a waypoint lattice from ever declaring coverage too early.
        if not any(self.footprint(p)-covered for p in locations):
            locations = sorted({(x,y) for y in range(self.height) for x in range(self.width)}-covered)
        for x, y in locations:
            cells = self.footprint((x,y))
            gain = len(cells-covered)
            if gain:
                choices.append(dict(candidate_id=f'{x},{y}', position=(x,y),
                    unseen_cells=gain, observed_water_cells=sum(p in evidence.flooded for p in cells),
                    flight_ticks=(chebyshev(pos,(x,y))+self.speed-1)//self.speed,
                    nearby_sightings=sum(chebyshev(g[0],(x,y)) <= 5
                        for g in evidence.groups.values() if g[1] in AVAILABLE)))
        return sorted(choices,key=lambda c:(-c['unseen_cells'],c['flight_ticks'],c['candidate_id']))[:10]

    # Keep flying a coverage leg while Claude chooses a later destination; ignore stale
    # preferences.
    def decide(self, tick, pos, evidence):
        result = self.worker.poll()
        if result:
            decision, options = result
            if decision.candidate_id not in options:
                self.worker.reject()
            else:
                candidate = options[decision.candidate_id]
                if self.footprint(candidate)-self.covered:
                    self.preference = (candidate, decision.explanation)
                else:
                    self.worker.stats['stale'] += 1
        if self.complete:
            self.goal, self.preference = None, None
            self.reason = 'Coverage complete: every grid cell checked'
            return None
        if not self.worker.provider:
            self.reason = self.worker.status
            return None
        if self.goal is None:
            if self.preference and self.footprint(self.preference[0])-self.covered:
                self.goal, self.reason = self.preference
                self.decision_source = 'claude'
            else:
                choices = self.candidates(pos,evidence)
                self.goal = tuple(choices[0]['position']) if choices else None
                self.reason = 'Continuing unvisited coverage while Claude updates search priorities'
                self.decision_source = 'coverage_execution'
            self.preference = None
        # Prefetch the next strategic choice while flying the current leg.
        # Treat only the current leg's footprint as projected coverage; actual
        # completion always uses real observations, never this prediction.
        if self.goal is not None and self.preference is None:
            projected = self.covered | self.footprint(self.goal)
            choices = self.candidates(self.goal,evidence,projected)
            if choices:
                self.worker.submit(dict(role='scout', tick=tick, position=pos,
                    current_goal=self.goal, search_candidates=choices,
                    known_flood_cells=len(evidence.flooded),
                    known_civilian_groups=[dict(group_id=gid,position=g[0],status=g[1],size=g[2])
                        for gid,g in sorted(evidence.groups.items())]),
                    {c['candidate_id']: tuple(c['position']) for c in choices})
        return self.goal


# Retain usable AI priorities while new discoveries or availability changes trigger replanning.
class RescuePlannerAgent:
    # Track accepted target revisions and explanations independently of in-flight requests.
    def __init__(self, worker):
        self.worker = worker
        self.priorities = []
        self.reason = 'Awaiting civilian evidence'
        self.confidence = 0.0
        self.signature = None
        self.approved_versions = {}
        self.explanations = {}

    # Accept unchanged portions of a delayed plan and refresh only when meaningful evidence
    # changes.
    def decide(self, context):
        current = {g['group_id']:g['revision'] for g in context['civilian_groups']}
        reported = context.get('reported_group_revisions',current)
        self.priorities = [gid for gid in self.priorities
            if gid in current and self.approved_versions.get(gid,current[gid]) == current[gid]]
        result = self.worker.poll()
        if result:
            decision, versions = result
            if set(decision.priorities) != set(versions):
                self.worker.reject()
                self.signature = None
            else:
                # A newly discovered group must not invalidate useful priorities
                # for unchanged existing groups. Changed/terminal targets alone
                # are discarded; they can never receive a stale assignment.
                valid = [gid for gid in decision.priorities if reported.get(gid) == versions[gid]]
                self.priorities = valid + [gid for gid in self.priorities if gid not in valid]
                for gid in valid:
                    self.approved_versions[gid] = versions[gid]
                    self.explanations[gid] = (decision.explanation,decision.confidence)
                self.reason,self.confidence = decision.explanation,decision.confidence
                if len(valid) != len(versions):
                    self.worker.stats['stale'] += 1
                if set(current)-set(valid) or len(valid) != len(versions):
                    self.signature = None
        signature = tuple((g['group_id'],g['revision'],g['size'],
            tuple((tid,route is None) for tid,route in sorted(g['route_estimates'].items())))
            for g in context['civilian_groups'])
        signature += tuple((t['team_id'],t['busy']) for t in context['teams'])
        if self.worker.last_error and self.worker.pending is None:
            self.signature = None
        if context['civilian_groups'] and signature != self.signature:
            if self.worker.submit(context,current):
                self.signature = signature
        if not context['civilian_groups']:
            self.signature = None


class CourierAgent:
    """Pursues reported positions, then searches nearby; never reads live remote positions."""
    # Seed the courier with briefing positions rather than granting access to hidden live
    # positions.
    def __init__(self, positions):
        self.positions = dict(positions)
        self.seen_tick = {tid: 0 for tid in positions}
        self.search_index = {tid: 0 for tid in positions}
        self.target_team = None
        self.reason = 'No undelivered orders'

    # Update a rendezvous position only from radio, direct contact, or a sensor sighting.
    def sight(self, tid, pos, tick):
        self.positions[tid], self.seen_tick[tid] = pos, tick
        self.search_index[tid] = 0

    # Approach the last report, then expand a local search if the moving team is no longer there.
    def destination(self, tid, drone_pos, width, height, radius):
        self.target_team = tid
        last = self.positions[tid]
        if chebyshev(drone_pos, last) > radius:
            return last
        # Reached a stale location without contact. Expand a deterministic search
        # around that report instead of following the team's hidden live position.
        self.search_index[tid] += 1
        index = self.search_index[tid]
        ring = 2 + (index - 1)//8 * 3
        directions = ((1,0),(1,1),(0,1),(-1,1),(-1,0),(-1,-1),(0,-1),(1,-1))
        dx, dy = directions[(index-1) % 8]
        return (max(0, min(width-1, last[0]+dx*ring)),
                max(0, min(height-1, last[1]+dy*ring)))


# Reserve one group for one team and distinguish undelivered orders from accepted work.
@dataclass
class Assignment:
    group_id: str
    team_id: str
    created_tick: int
    reason: str
    confidence: float
    phase: str = 'pending_delivery'
    expected_free_tick: int = 0
    ai_ranked: bool = True


# Coordinate scout, planner, courier, and local teams while keeping ownership and physical
# execution deterministic.
class DroneAgentSystem:
    # Create agent-local state, bounded Claude workers, and independent offline-only random
    # streams.
    def __init__(self, cfg, provider=None, clock=time.monotonic, pool=None):
        self.cfg, self.clock = cfg, clock
        self.provider = provider
        if self.provider is None:
            try:
                self.provider = ClaudeProvider(model=os.environ.get('FLOODNET_CLAUDE_MODEL', 'claude-haiku-5-5'),
                                               max_tokens=512, max_requests=100)
            except ValueError:
                pass
        self.pool = pool or ThreadPoolExecutor(max_workers=2, thread_name_prefix='drone-agents')
        worker = lambda schema, prompt: DecisionWorker(self.provider, self.pool, schema, prompt, clock)
        self.scout = ScoutAgent(worker(ScoutDecision, SCOUT_PROMPT), cfg.width, cfg.height, cfg.drone_sense_radius, cfg.drone_speed)
        self.planner = RescuePlannerAgent(worker(RescueDecision, PLANNER_PROMPT))
        self.courier = CourierAgent({t.team_id: tup(t.position) for t in cfg.teams})
        self.evidence = Evidence()
        self.teams = {t.team_id: dict(position=tup(t.position), capacity=t.capacity,
            carried=t.carried_civilians, order=None, reported_tick=0) for t in cfg.teams}
        self.orders = {t.team_id: None for t in cfg.teams}
        # Separate seeded streams keep offline wandering reproducible without
        # consuming world/AI randomness or changing any online decisions.
        self._wander_rng = {t.team_id: random.Random(f'{cfg.seed}/offline/{t.team_id}') for t in cfg.teams}
        self.wandering = set()
        self.assignments = {}
        self.queued_at = {}
        self.routes = {t.team_id: [] for t in cfg.teams}
        self.history = {t.team_id: [tup(t.position)] for t in cfg.teams}
        self.contact_radius = 1
        self.contacted = set()
        self._next_status_check_tick = 0
        self.events = []
        self.delivered_count = 0
        self.last_delivery_tick = None
        self.flight_goal = None
        self.mode = 'scout'
        self.reason = 'Claude scout and rescue planner ready' if self.provider else 'Configure API_KEY to enable Claude agents'
        self.returning = False
        self.closed = False
        self._contact_fingerprints = {}
        self._last_status = None
        self._last_priority = None
        self._blocked_teams = set()

    # Queue a plain operational event for the manager to timestamp and publish.
    def emit(self, tick, title, description, category='ai', severity='info'):
        self.events.append(dict(tick=tick, title=title, description=description,
                                category=category, severity=severity))

    # Invalidate model replies and flight preferences after an operator or connectivity change.
    def invalidate(self):
        self.scout.worker.invalidate()
        self.planner.worker.invalidate()
        self.scout.goal = None
        self.scout.preference = None
        self.planner.signature = None
        self.flight_goal = None

    # Prevent further drone work and shut down pending background planning safely.
    def close(self):
        self.closed = True
        self.invalidate()
        self.pool.shutdown(wait=False, cancel_futures=True)

    # Give the operator's return command priority over scouting and courier flight.
    def return_home(self):
        self.invalidate()
        self.returning = True
        self.mode = 'return'
        self.flight_goal = tup(self.cfg.drones[0].position)
        self.reason = 'Operator commanded return to launch base'

    # Resume autonomous flight with fresh preferences while retaining rescue-task ownership.
    def launch(self):
        self.invalidate()
        self.returning = False

    # Import only a team report that has actually reached the coordinator.
    def _merge_agent(self, aid, agent, tick):
        changed = self.evidence.merge(agent.known_groups, agent.known_group_versions, agent.known_flooded)
        for gid in changed:
            if self.evidence.groups[gid][1] in AVAILABLE:
                self.emit(tick, 'Civilian Evidence Received', f'{aid} reported {gid}. Rescue planner notified.')

    # Refresh availability at real communication and release reported completed task ownership.
    def _report(self, tid, world, tick):
        team = world.team_state(tid)
        self.teams[tid] = dict(position=tup(team.position), capacity=team.capacity,
            carried=team.carried_civilians, order=self.orders[tid], reported_tick=tick)
        self.courier.sight(tid, tup(team.position), tick)
        for gid, task in list(self.assignments.items()):
            if task.team_id == tid and task.phase == 'active' and not self.orders[tid] and not team.carried_civilians:
                del self.assignments[gid]
                self.emit(tick, 'Team Available', f'{tid} reported free after completing or releasing its task.', 'team')

    # Revalidate a reserved order against the receiving team's capacity, knowledge, and current
    # work.
    def _deliver(self, tid, world, agents, tick, radio):
        for gid, task in list(self.assignments.items()):
            if task.team_id != tid or task.phase != 'pending_delivery':
                continue
            team = world.team_state(tid)
            known = agents[tid].known_groups.get(gid)
            path = (interaction_path(tup(team.position), known[0], agents[tid].known_flooded,
                    self.cfg.width, self.cfg.height) if known else None)
            if (self.orders[tid] or team.carried_civilians or not known or known[1] not in AVAILABLE
                    or known[2] > team.capacity or path is None):
                del self.assignments[gid]
                self.emit(tick, 'Order Revalidation Required', f'{tid} cannot accept {gid}; task returned to planner.', 'team', 'warning')
                continue
            task.phase = 'active'
            endpoint = path[-1] if path else tup(team.position)
            home = interaction_path(endpoint, tup(world.shelter.position), agents[tid].known_flooded,
                                    self.cfg.width, self.cfg.height)
            task.expected_free_tick = tick + len(path) + (len(home) if home is not None else 12) + 2
            self.orders[tid] = gid
            self.teams[tid]['order'] = gid
            if not radio:
                self.delivered_count += 1
                self.last_delivery_tick = tick
            self.emit(tick, 'Rescue Order Delivered', f'{tid} assigned {gid} via {"radio" if radio else "physical drone contact"}. {task.reason}', 'team', 'success')

    # Apply local sensing and allow cross-agent knowledge transfer only through radio or physical
    # contact.
    def sense(self, world, agents, observations, radio):
        tick = world.tick
        drone = world.drones['drone-1']
        self.contacted = set()
        for tid in world.teams:
            agents[tid].observe(observations[tid])
        if drone.enabled:
            changed = self.evidence.observe(observations[drone.drone_id])
            self.scout.observe_position(tup(drone.position))
            for gid in changed:
                if self.evidence.groups[gid][1] in AVAILABLE:
                    self.emit(tick, 'Scout Discovered Civilians', f'Drone sensors located {gid}; rescue planner notified.', 'drone', 'success')
            for obs in observations[drone.drone_id]:
                if obs.entity.entity_type == EntityType.RESCUE_TEAM:
                    self.courier.sight(obs.entity.entity_id, tup(obs.position), tick)
        contacts = [tid for tid, team in world.teams.items()
                    if drone.enabled and chebyshev(tup(team.position), tup(drone.position)) <= self.contact_radius]
        recipients = list(world.teams) if radio else contacts
        if not radio and contacts:
            self._next_status_check_tick = tick + 4
        for tid in recipients:
            self._merge_agent(tid, agents[tid], tick)
            self._report(tid, world, tick)
        # Merge every received report before forwarding, preserving provenance.
        for tid in recipients:
            agent = agents[tid]
            before = (frozenset(agent.known_flooded), tuple(sorted(agent.known_groups.items())))
            agent.known_flooded.update(self.evidence.flooded)
            agent.merge_groups(self.evidence.groups, self.evidence.versions)
            after = (frozenset(agent.known_flooded), tuple(sorted(agent.known_groups.items())))
            if not radio and before != after and self._contact_fingerprints.get(tid) != after:
                self.delivered_count += 1
                self.last_delivery_tick = tick
                self.emit(tick, 'Scout Intelligence Delivered', f'Drone physically updated {tid} with civilian and flood evidence.', 'drone', 'success')
            self._contact_fingerprints[tid] = after
            self.contacted.add(tid)
        for gid, task in list(self.assignments.items()):
            known = self.evidence.groups.get(gid)
            if known and known[1] in TERMINAL:
                del self.assignments[gid]
                # Local orders are cleared only by a team's own evidence or a
                # real communication, never by unseen remote world changes.
                if task.team_id in recipients and self.orders[task.team_id] == gid:
                    self.orders[task.team_id] = None
        for tid in recipients:
            self._deliver(tid, world, agents, tick, radio)

    # Build an evidence-only Claude view; route estimates are not hidden flood deadlines.
    def planning_context(self, tick):
        groups = []
        for gid, (pos, status, size) in sorted(self.evidence.groups.items()):
            if status not in AVAILABLE or gid in self.assignments:
                continue
            routes = {}
            for tid, team in self.teams.items():
                if size > team['capacity']:
                    routes[tid] = None
                    continue
                path = interaction_path(team['position'], pos, self.evidence.flooded, self.cfg.width, self.cfg.height)
                home = interaction_path(pos, tup(self.cfg.shelter.position), self.evidence.flooded, self.cfg.width, self.cfg.height)
                routes[tid] = None if path is None or home is None else dict(to_group=len(path), to_shelter=len(home))
            groups.append(dict(group_id=gid, position=pos, size=size,
                revision=self.evidence.versions.get(gid, (-1, -1))[1],
                nearest_observed_water=min((manhattan(pos, p) for p in self.evidence.flooded), default=None),
                route_estimates=routes))
        return dict(role='rescue_planner', tick=tick, civilian_groups=groups,
            reported_group_revisions={gid:self.evidence.versions.get(gid,(-1,-1))[1]
                for gid,g in self.evidence.groups.items() if g[1] in AVAILABLE},
            teams=[dict(team_id=tid, position=t['position'], capacity=t['capacity'],
                busy=bool(t['carried'] or t['order'] or any(a.team_id == tid for a in self.assignments.values())),
                reported_tick=t['reported_tick']) for tid, t in sorted(self.teams.items())],
            objective='Maximize people delivered alive to shelter; water proximity is uncertain risk')

    # Use AI priorities and the standing queue to assign the closest eligible free team exactly
    # once.
    def dispatch(self, world, agents, radio):
        tick = world.tick
        if not self.provider:
            return
        # A delayed AI result may validate an order already issued under the
        # standing policy. Update its explanation without changing its owner or
        # redirecting the team; only unchanged reported targets qualify.
        for gid,task in self.assignments.items():
            revision = self.evidence.versions.get(gid,(-1,-1))[1]
            if self.planner.approved_versions.get(gid) == revision and gid in self.planner.explanations:
                task.reason,task.confidence = self.planner.explanations[gid]
                task.ai_ranked = True
        waiting = [gid for gid,(_,status,_) in self.evidence.groups.items()
                   if status in AVAILABLE and gid not in self.assignments]
        for gid in waiting:
            self.queued_at.setdefault(gid,tick)
        # Claude orders the queue when available. Ordinary availability handoffs
        # must not stop when the model is slow: unranked discoveries retain their
        # arrival order under the operator's standing dispatch policy.
        ranked = [gid for gid in self.planner.priorities if gid in waiting]
        queue = ranked + sorted((gid for gid in waiting if gid not in ranked),
                                key=lambda gid:(self.queued_at[gid],gid))
        for gid in queue:
            # One-tick planning window for a brand-new discovery. This normally
            # gives Claude first choice at 20s ticks; old queued work is handed
            # to a newly free team immediately even if a refresh is pending.
            if gid not in ranked and self.planner.worker.pending and self.queued_at[gid] == tick:
                continue
            known = self.evidence.groups.get(gid)
            if not known or known[1] not in AVAILABLE or gid in self.assignments:
                continue
            pos, _, size = known
            choices = []
            for tid, team in self.teams.items():
                if team['carried'] or team['order'] or any(a.team_id == tid for a in self.assignments.values()):
                    continue
                if size > team['capacity']:
                    continue
                path = interaction_path(team['position'], pos, self.evidence.flooded, self.cfg.width, self.cfg.height)
                if path is not None:
                    endpoint = path[-1] if path else team['position']
                    home = interaction_path(endpoint, tup(self.cfg.shelter.position), self.evidence.flooded, self.cfg.width, self.cfg.height)
                    if home is not None:
                        choices.append((len(path), tid))
            if not choices:
                continue
            _, tid = min(choices)
            ai_ranked = gid in ranked
            reason,confidence = (self.planner.explanations.get(gid,(self.planner.reason,self.planner.confidence))
                if ai_ranked else ('Standing dispatch policy: eligible queued rescue; Claude priorities pending.',0.0))
            self.assignments[gid] = Assignment(gid,tid,tick,reason,confidence,ai_ranked=ai_ranked)
            self.emit(tick, 'Rescue Task Reserved', f'{gid} reserved for closest eligible free team {tid}.', 'team')
            if radio or tid in self.contacted:
                self._deliver(tid, world, agents, tick, radio)

    # Prioritize flood escape, passenger delivery, and accepted orders; only idle offline teams
    # wander.
    def team_action(self, world, tid, agent, radio=True):
        self.wandering.discard(tid)
        team, tick = world.team_state(tid), world.tick
        pos = tup(team.position)
        self.routes[tid] = []
        action = lambda kind, **kw: ActionProposal(team_id=tid, action_type=kind, based_on_world_tick=tick, **kw)
        if pos in agent.known_flooded:
            for dx, dy in NEIGHBOURS:
                nxt = (pos[0]+dx, pos[1]+dy)
                if world.in_bounds(nxt) and nxt not in agent.known_flooded:
                    self.routes[tid] = [nxt]
                    return action(ActionType.MOVE, target_position=gp(nxt), explanation='Escape to adjacent dry ground')
            return action(ActionType.WAIT, explanation='Stranded; no adjacent dry ground')
        if team.carried_civilians:
            target, kind = tup(world.shelter.position), ActionType.DROP_OFF
            entity = world.shelter.shelter_id
        else:
            entity = self.orders[tid]
            known = agent.known_groups.get(entity)
            if not known or known[1] not in AVAILABLE:
                self.orders[tid] = None
                if not radio:
                    # Only an idle, empty offline team wanders. Delivered orders,
                    # passenger transport, and flood escape keep their priority.
                    neighbours = [(pos[0]+dx,pos[1]+dy) for dx,dy in NEIGHBOURS]
                    safe = [p for p in neighbours if world.in_bounds(p) and p not in agent.known_flooded]
                    if safe:
                        target = self._wander_rng[tid].choice(safe)
                        self.routes[tid] = [target]
                        self.wandering.add(tid)
                        return action(ActionType.MOVE,target_position=gp(target),
                                      explanation='Radio offline: wandering on locally observed dry ground')
                    return action(ActionType.WAIT,explanation='Radio offline: no adjacent dry ground for wandering')
                return action(ActionType.WAIT, explanation='Awaiting a delivered rescue order')
            target, kind = known[0], ActionType.PICKUP
        path = interaction_path(pos, target, agent.known_flooded, self.cfg.width, self.cfg.height)
        self.routes[tid] = path or []
        if path is None:
            if tid not in self._blocked_teams:
                self.emit(tick, 'Rescue Route Blocked', f'{tid} has no locally known dry route; task needs updated evidence or a new plan.', 'team', 'warning')
                self._blocked_teams.add(tid)
            if not team.carried_civilians:
                self.orders[tid] = None
            return action(ActionType.WAIT, explanation='No dry route; awaiting updated plan')
        self._blocked_teams.discard(tid)
        if not path:
            return action(kind, target_entity_id=entity, explanation='Execute delivered rescue plan')
        return action(ActionType.MOVE, target_position=gp(path[0]), target_entity_id=entity,
                      explanation='Follow dry route for assigned rescue')

    # Issue one flight command, prioritizing operator return and urgent orders without starving
    # coverage.
    def drone_action(self, world, agents, radio):
        tick, drone = world.tick, world.drones['drone-1']
        pos = tup(drone.position)
        wait = lambda: ActionProposal(team_id=drone.drone_id, action_type=ActionType.WAIT,
                                      based_on_world_tick=tick, explanation=self.reason)
        if not drone.enabled or self.closed:
            return wait()
        if self.returning:
            self.mode = 'return'
            target = tup(self.cfg.drones[0].position)
            if pos == target:
                drone.enabled = False
                self.flight_goal = None
                self.reason = 'Landed at launch base; awaiting launch'
                return wait()
        else:
            context = self.planning_context(tick)
            self.planner.decide(context)
            self.dispatch(world, agents, radio)
            priorities = tuple(self.planner.priorities)
            if priorities and priorities != self._last_priority:
                self.emit(tick, 'Rescue Planner Priorities', f'{", ".join(priorities)}. {self.planner.reason}')
            self._last_priority = priorities
            # Courier orders take precedence; collect busy-team status when work
            # is queued. Team positions below are reports/sightings, not truth.
            pending = sorted((a.created_tick, a.team_id) for a in self.assignments.values() if a.phase == 'pending_delivery')
            expected = {a.team_id: a.expected_free_tick for a in self.assignments.values() if a.phase == 'active'}
            stale = sorted((t['reported_tick'], tid) for tid, t in self.teams.items()
                           if tick-t['reported_tick'] >= 6 and tick >= expected.get(tid, t['reported_tick']+12)
                           and tid not in self.contacted)
            recipient = pending[0][1] if pending else (stale[0][1] if context['civilian_groups'] and stale
                and tick >= self._next_status_check_tick
                and (self.scout.goal is None or self.scout.complete) else None)
            if not radio and recipient:
                self.mode = 'courier'
                self.reason = f'Courier approaching {recipient} to deliver orders or collect availability'
                target = self.courier.destination(recipient, pos, self.cfg.width, self.cfg.height, self.contact_radius)
            else:
                self.mode = 'scout'
                self.courier.target_team = None
                target = self.scout.decide(tick, pos, self.evidence)
                self.reason = f'Scout: {self.scout.reason}'
            status = (self.mode, self.reason, self.planner.worker.status)
            if status != self._last_status:
                self.emit(tick, 'Drone Agent Mission', f'{self.mode}: {self.reason}. Planner: {self.planner.worker.status}', 'drone')
                self._last_status = status
        self.flight_goal = target
        if target is None:
            return wait()
        speed = self.cfg.drone_speed
        step = (pos[0]+max(-speed, min(speed, target[0]-pos[0])),
                pos[1]+max(-speed, min(speed, target[1]-pos[1])))
        return ActionProposal(team_id=drone.drone_id, action_type=ActionType.MOVE,
                              target_position=gp(step), based_on_world_tick=tick, explanation=self.reason)

    # Apply authoritative completion feedback and record actual team trails after validation.
    def apply_results(self, world, proposals, outcome):
        actions = {p.action_id: p for p in proposals}
        for result in outcome.results:
            if result.team_id not in self.orders:
                continue
            action = actions[result.action_id]
            if result.status == ActionStatus.COMPLETED and action.action_type == ActionType.DROP_OFF:
                self.orders[result.team_id] = None
            pos = world.agent_pos(result.team_id)
            if self.history[result.team_id][-1] != pos:
                self.history[result.team_id].append(pos)

    # Adapt undelivered reservations to the existing dashboard message-counter contract.
    def pending_messages(self):
        return [dict(messageId=f'order_{a.created_tick}_{a.group_id}_{a.team_id}', senderId='rescue_planner',
            originNeighbourhood='drone', destinationNeighbourhood=a.team_id, type='task_claim',
            createdTick=a.created_tick, data={}) for a in self.assignments.values() if a.phase == 'pending_delivery']

    # Show the actual active or pending plan and explicitly label standing-policy fallback.
    def recommendation(self, tid, team, tick):
        task = next((a for a in self.assignments.values() if a.team_id == tid), None)
        carrying = bool(team.carried_civilians)
        active = self.orders[tid]
        target = self.cfg.shelter.shelter_id if carrying else (active or (task.group_id if task else None))
        return dict(teamId=tid, recommendedTargetId=target, targetDescription=target or 'Awaiting scout evidence',
            recommendedAction=('Deliver passengers to shelter' if carrying else
                'Execute assigned rescue' if active else 'Await physical courier order' if task else 'Stand by for rescue assignment'),
            reasoning=task.reason if task else self.planner.worker.status,
            confidence=round(task.confidence*100) if task else 0,
            missingInformation='Only locally observed or physically delivered evidence is available.',
            isAiFallback=bool(task and not task.ai_ranked), generatedTick=task.created_tick if task else tick)

    # Expose mission, coverage, ownership, and safe API diagnostics for inspection.
    def state(self):
        return dict(mission=self.mode, scout=dict(goal=self.scout.goal, status=self.scout.worker.status,
                    coveredCells=len(self.scout.covered), totalCells=self.cfg.width*self.cfg.height,
                    coverageComplete=self.scout.complete, decisionSource=self.scout.decision_source,
                    diagnostics=self.scout.worker.diagnostics()),
            planner=dict(priorities=self.planner.priorities,status=self.planner.worker.status,
                diagnostics=self.planner.worker.diagnostics()),
            courier=dict(targetTeam=self.courier.target_team, contactRadius=self.contact_radius),
            api=dict(requests=(self.provider.calls if isinstance(getattr(self.provider,'calls',None),int)
                    else self.scout.worker.stats['requests']+self.planner.worker.stats['requests']),
                requestLimit=getattr(self.provider,'max_requests',None),
                usage=dict(getattr(self.provider,'usage',{}))),
            queuedTasks=[gid for gid,g in self.evidence.groups.items() if g[1] in AVAILABLE and gid not in self.assignments],
            assignments=[dict(groupId=a.group_id,teamId=a.team_id,phase=a.phase,aiRanked=a.ai_ranked)
                         for a in self.assignments.values()])
