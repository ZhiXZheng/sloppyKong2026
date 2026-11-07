/**
 * Standalone browser fallback helpers. The live Python controller owns drone-directed rescue
 * assignment and offline wandering.
 */
import {
  AIRecommendation,
  CivilianGroup,
  GridPosition,
  RescueTeam,
  Shelter,
  SimulationEvent,
  TaskClaim,
  TeamBeliefMap,
  WorldGridCell
} from '../types/simulation';

/**
 * Compute a dry, cardinal route. No route means wait; never cross water.
 */
export function findPath(
  start: GridPosition,
  goal: GridPosition,
  cells: WorldGridCell[][]
): GridPosition[] {
  // Simple Breadth-First-Search or Manhattan steps
  if (start.x === goal.x && start.y === goal.y) {
    return [];
  }

  const queue: { pos: GridPosition; path: GridPosition[] }[] = [
    { pos: start, path: [] }
  ];
  const visited = new Set<string>();
  visited.add(`${start.x},${start.y}`);

  // Limit search depth to prevent lag
  let iterations = 0;
  const maxIterations = 600;

  while (queue.length > 0 && iterations < maxIterations) {
    iterations++;
    const current = queue.shift()!;
    const { pos, path } = current;

    if (pos.x === goal.x && pos.y === goal.y) {
      return path;
    }

    // 4 cardinal directions (prefer moving towards goal first)
    const dirs = [
      { dx: 0, dy: -1, dir: 'N' },
      { dx: 1, dy: 0, dir: 'E' },
      { dx: 0, dy: 1, dir: 'S' },
      { dx: -1, dy: 0, dir: 'W' }
    ].sort((a, b) => {
      const distA = Math.hypot(pos.x + a.dx - goal.x, pos.y + a.dy - goal.y);
      const distB = Math.hypot(pos.x + b.dx - goal.x, pos.y + b.dy - goal.y);
      return distA - distB;
    });

    for (const d of dirs) {
      const nx = pos.x + d.dx;
      const ny = pos.y + d.dy;
      const key = `${nx},${ny}`;

      if (nx >= 0 && nx < cells[0].length && ny >= 0 && ny < cells.length && !visited.has(key)) {
        visited.add(key);
        const cell = cells[ny][nx];

        // All flooded cells are impassable, including roads and the goal.
        if (cell.isFlooded) continue;

        queue.push({
          pos: { x: nx, y: ny },
          path: [...path, { x: nx, y: ny }]
        });
      }
    }
  }

  // No dry route: remain in place instead of walking through the obstacle.
  return [];
}

/**
 * Determine cardinal direction from current to next position
 */
export function getDirection(from: GridPosition, to: GridPosition): 'N' | 'S' | 'E' | 'W' | 'IDLE' {
  if (to.y < from.y) return 'N';
  if (to.y > from.y) return 'S';
  if (to.x > from.x) return 'E';
  if (to.x < from.x) return 'W';
  return 'IDLE';
}

/**
 * Update agent AI recommendation based on its own belief map
 */
export function generateTeamRecommendation(
  team: RescueTeam,
  beliefMap: TeamBeliefMap,
  shelter: Shelter,
  radioConnected: boolean,
  currentTick: number
): AIRecommendation {
  if (team.carriedCivilians > 0) {
    return {
      teamId: team.teamId,
      recommendedTargetId: shelter.shelterId,
      targetDescription: shelter.name,
      recommendedAction: 'Transport Evacuees to Shelter',
      reasoning: `Team is carrying ${team.carriedCivilians} civilians. Immediate transport to safe haven at (${shelter.position.x},${shelter.position.y}) recommended.`,
      confidence: radioConnected ? 98 : 85,
      missingInformation: radioConnected
        ? 'Route fully verified via operational link.'
        : 'Transit route unverified by central AI due to partition.',
      isAiFallback: !radioConnected,
      generatedTick: currentTick
    };
  }

  // Look for known civilians in team's private belief map
  const availableGroups = Object.values(beliefMap.knownCivilians).filter(
    c => c.status === 'available' || c.status === 'claimed'
  );

  if (availableGroups.length === 0) {
    return {
      teamId: team.teamId,
      recommendedTargetId: undefined,
      targetDescription: 'Sector Reconnaissance',
      recommendedAction: 'Patrol & Expand Sensor Coverage',
      reasoning: 'No known unrescued civilians in current belief map. Conduct exploratory patrol.',
      confidence: radioConnected ? 82 : 65,
      missingInformation: 'Large portions of the urban grid remain unobserved.',
      isAiFallback: !radioConnected,
      generatedTick: currentTick
    };
  }

  // Nearest known group
  let nearest = availableGroups[0];
  let minDist = Math.hypot(
    team.position.x - nearest.position.x,
    team.position.y - nearest.position.y
  );

  for (let i = 1; i < availableGroups.length; i++) {
    const g = availableGroups[i];
    const dist = Math.hypot(
      team.position.x - g.position.x,
      team.position.y - g.position.y
    );
    if (dist < minDist) {
      minDist = dist;
      nearest = g;
    }
  }

  const isBorderGroup = nearest.groupId === 'civ_2';

  const reasoning = radioConnected
    ? `${nearest.groupId} is the optimal reachable target (${minDist.toFixed(1)} cells). Centrally verified.`
    : `Heuristic rule selected nearest observed group ${nearest.groupId} (${minDist.toFixed(1)} cells). Radio offline: operating on local belief.`;

  const missingInfo = !radioConnected
    ? isBorderGroup
      ? 'WARNING: Contested border target. Cannot verify if other rescue unit is en route.'
      : 'Radio link disconnected. Operating on cached local sensor observations.'
    : 'Local flood telemetry continuously monitored.';

  return {
    teamId: team.teamId,
    recommendedTargetId: nearest.groupId,
    targetDescription: `Target: ${nearest.groupId} (${nearest.size} people)`,
    recommendedAction: `Deploy to rescue at (${nearest.position.x},${nearest.position.y})`,
    reasoning,
    confidence: radioConnected ? 93 : 74,
    missingInformation: missingInfo,
    isAiFallback: !radioConnected,
    generatedTick: currentTick
  };
}

/**
 * Step an agent forward: pick target, move, pickup, drop off
 */
export function stepAgent(
  team: RescueTeam,
  beliefMap: TeamBeliefMap,
  civilians: CivilianGroup[],
  shelter: Shelter,
  cells: WorldGridCell[][],
  radioConnected: boolean,
  currentTick: number,
  timestamp: string
): {
  events: SimulationEvent[];
  newClaim?: TaskClaim;
} {
  const events: SimulationEvent[] = [];
  let newClaim: TaskClaim | undefined;

  // 1. Deliver to shelter if carrying civilians
  if (team.carriedCivilians > 0) {
    const distToShelter = Math.hypot(
      team.position.x - shelter.position.x,
      team.position.y - shelter.position.y
    );

    if (distToShelter <= 1) {
      // At shelter: drop off!
      const rescuedCount = team.carriedCivilians;
      shelter.occupants += rescuedCount;

      for (const gid of team.carriedGroupIds) {
        const group = civilians.find(c => c.groupId === gid);
        if (group) {
          group.status = 'delivered';
          group.deliveredToShelterId = shelter.shelterId;
        }
        if (beliefMap.knownCivilians[gid]) {
          beliefMap.knownCivilians[gid].status = 'delivered';
        }
        if (beliefMap.knownClaims[gid]) {
          beliefMap.knownClaims[gid].status = 'completed';
        }
      }

      team.carriedCivilians = 0;
      team.carriedGroupIds = [];
      team.state = 'idle';
      team.currentTargetId = undefined;
      team.plannedRoute = [];

      events.push({
        id: `ev_drop_${team.teamId}_${currentTick}`,
        tick: currentTick,
        timestamp,
        category: 'rescue',
        severity: 'success',
        title: `${team.name} Delivered Civilians`,
        description: `Successfully brought ${rescuedCount} civilians safely to ${shelter.name}. Current shelter occupants: ${shelter.occupants}.`
      });

      return { events, newClaim };
    } else {
      // Move towards shelter
      team.state = 'delivering';
      const path = findPath(team.position, shelter.position, cells);
      team.plannedRoute = path;
      if (path.length > 0) {
        const nextPos = path[0];
        team.direction = getDirection(team.position, nextPos);
        team.position = nextPos;
        team.completedRoute.push(nextPos);
      }
      return { events, newClaim };
    }
  }

  // 2. Not carrying civilians: find best target from own belief map
  const knownAvailable = Object.values(beliefMap.knownCivilians).filter(
    c => c.status === 'available' || (c.status === 'claimed' && c.claimedBy === team.teamId)
  );

  if (knownAvailable.length === 0) {
    team.state = 'idle';
    return { events, newClaim };
  }

  // Sort by distance
  knownAvailable.sort((a, b) => {
    const da = Math.hypot(team.position.x - a.position.x, team.position.y - a.position.y);
    const db = Math.hypot(team.position.x - b.position.x, team.position.y - b.position.y);
    return da - db;
  });

  const targetCivilianInfo = knownAvailable[0];
  const targetGroup = civilians.find(c => c.groupId === targetCivilianInfo.groupId);
  if (!targetGroup) return { events, newClaim };

  // Set target and claim
  if (team.currentTargetId !== targetGroup.groupId) {
    team.currentTargetId = targetGroup.groupId;

    newClaim = {
      claimId: `claim_${team.teamId}_${targetGroup.groupId}_${currentTick}`,
      teamId: team.teamId,
      civilianGroupId: targetGroup.groupId,
      claimedAtTick: currentTick,
      status: radioConnected ? 'confirmed' : 'provisional',
      reason: radioConnected
        ? 'Assigned through central coordination'
        : 'Provisional claim during network partition'
    };

    beliefMap.knownClaims[targetGroup.groupId] = newClaim;
    targetGroup.status = 'claimed';
    targetGroup.claimedByTeamId = team.teamId;

    events.push({
      id: `ev_claim_${team.teamId}_${currentTick}`,
      tick: currentTick,
      timestamp,
      category: 'team',
      severity: radioConnected ? 'info' : 'warning',
      title: `${team.name} Claimed Target`,
      description: `${team.name} targeted ${targetGroup.name} (${targetGroup.size} civilians) at (${targetGroup.position.x},${targetGroup.position.y}) [${newClaim.status.toUpperCase()}].`
    });
  }

  // Check if at civilian position: PICK UP!
  const distToTarget = Math.hypot(
    team.position.x - targetGroup.position.x,
    team.position.y - targetGroup.position.y
  );

  if (distToTarget <= 0.5) {
    if (targetGroup.status !== 'picked_up' && targetGroup.status !== 'delivered') {
      targetGroup.status = 'picked_up';
      targetGroup.pickedUpByTeamId = team.teamId;
      team.carriedCivilians = targetGroup.size;
      team.carriedGroupIds = [targetGroup.groupId];
      team.state = 'rescuing';

      beliefMap.knownCivilians[targetGroup.groupId].status = 'picked_up';

      events.push({
        id: `ev_pickup_${team.teamId}_${currentTick}`,
        tick: currentTick,
        timestamp,
        category: 'rescue',
        severity: 'success',
        title: `${team.name} Evacuated Civilians`,
        description: `Reached ${targetGroup.name}. Secured ${targetGroup.size} persons aboard rescue craft. Rerouting to ${shelter.name}.`
      });

      return { events, newClaim };
    }
  }

  // Move towards target
  team.state = 'moving';
  const path = findPath(team.position, targetGroup.position, cells);
  team.plannedRoute = path;
  if (path.length > 0) {
    const nextPos = path[0];
    team.direction = getDirection(team.position, nextPos);
    team.position = nextPos;
    team.completedRoute.push(nextPos);
  }

  return { events, newClaim };
}
