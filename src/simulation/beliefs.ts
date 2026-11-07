import {
  CellObservation,
  CivilianGroup,
  GridPosition,
  RescueTeam,
  Shelter,
  TeamBeliefMap,
  WorldGridCell
} from '../types/simulation';

const SENSOR_RADIUS = 3;

/**
 * Scan surroundings around a team's current position and generate new observations.
 */
export function scanSurroundings(
  team: RescueTeam,
  cells: WorldGridCell[][],
  civilians: CivilianGroup[],
  shelter: Shelter,
  currentTick: number
): { observations: CellObservation[]; detectedCivilians: CivilianGroup[] } {
  const observations: CellObservation[] = [];
  const detectedCivilians: CivilianGroup[] = [];

  const { x: tx, y: ty } = team.position;

  for (let dy = -SENSOR_RADIUS; dy <= SENSOR_RADIUS; dy++) {
    for (let dx = -SENSOR_RADIUS; dx <= SENSOR_RADIUS; dx++) {
      const x = tx + dx;
      const y = ty + dy;

      // Check bounds
      if (x < 0 || x >= 20 || y < 0 || y >= 20) continue;

      // Distance check (euclidean <= 3.5)
      if (Math.hypot(dx, dy) > 3.6) continue;

      const cell = cells[y][x];

      // Check if civilian group is on this cell
      const civ = civilians.find(c => c.position.x === x && c.position.y === y);
      if (civ) {
        detectedCivilians.push(civ);
      }

      // Check if shelter is on this cell
      const isShelter = shelter.position.x === x && shelter.position.y === y;

      let state: CellObservation['state'] = 'safe';
      if (isShelter) {
        state = 'shelter';
      } else if (civ && civ.status !== 'delivered') {
        state = 'civilian';
      } else if (cell.isFlooded && cell.waterDepth >= 2 && !cell.isSubmergedRoad) {
        state = 'flooded';
      } else {
        state = 'safe';
      }

      observations.push({
        x,
        y,
        state,
        waterDepth: cell.waterDepth,
        civilianGroupId: civ?.groupId,
        civilianStatus: civ?.status,
        observedAtTick: currentTick,
        observerId: team.teamId
      });
    }
  }

  return { observations, detectedCivilians };
}

/**
 * Merge observations into a team's belief map.
 * Invariant: Older observations must never overwrite newer observations.
 */
export function applyObservationsToBelief(
  beliefMap: TeamBeliefMap,
  observations: CellObservation[],
  currentTick: number
): { updatedCount: number; newCivilianDiscovered: boolean } {
  let updatedCount = 0;
  let newCivilianDiscovered = false;

  for (const obs of observations) {
    const key = `${obs.x},${obs.y}`;
    const existing = beliefMap.grid[key];

    // Check monotonic freshness
    if (!existing || obs.observedAtTick >= existing.observedAtTick) {
      beliefMap.grid[key] = { ...obs };
      updatedCount++;

      // If observation found a civilian
      if (obs.civilianGroupId) {
        const known = beliefMap.knownCivilians[obs.civilianGroupId];
        if (!known) {
          newCivilianDiscovered = true;
        }

        beliefMap.knownCivilians[obs.civilianGroupId] = {
          groupId: obs.civilianGroupId,
          position: { x: obs.x, y: obs.y },
          size: 0, // Will be updated if civilian metadata is present
          status: obs.civilianStatus || 'available',
          observedTick: obs.observedAtTick,
          observerId: obs.observerId
        };
      }
    }
  }

  if (updatedCount > 0) {
    beliefMap.version += 1;
    beliefMap.lastUpdatedTick = currentTick;
  }

  return { updatedCount, newCivilianDiscovered };
}

/**
 * Sync known civilian full metadata into belief map
 */
export function updateKnownCivilianMetadata(
  beliefMap: TeamBeliefMap,
  civilians: CivilianGroup[],
  observerId: string,
  tick: number
) {
  for (const civ of civilians) {
    if (beliefMap.knownCivilians[civ.groupId]) {
      beliefMap.knownCivilians[civ.groupId] = {
        groupId: civ.groupId,
        position: civ.position,
        size: civ.size,
        status: civ.status,
        claimedBy: civ.claimedByTeamId,
        observedTick: tick,
        observerId
      };
    }
  }
}
