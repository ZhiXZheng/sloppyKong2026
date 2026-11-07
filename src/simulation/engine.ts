import {
  SimulationWorld,
  SimulationEvent,
  CivilianGroup
} from '../types/simulation';
import {
  applyObservationsToBelief,
  scanSurroundings,
  updateKnownCivilianMetadata
} from './beliefs';
import {
  stepAgent,
  generateTeamRecommendation
} from './agents';
import { updateDroneStep } from './drone';
import {
  handleDirectRadioComms,
  queueOutgoingMessage
} from './communications';
import {
  detectClaimConflicts,
  resolveClaimConflict
} from './conflictResolution';

/**
 * Format simulation tick as HH:MM:SS starting from 15:00:00
 */
export function formatSimTimestamp(tick: number): string {
  const totalSeconds = tick * 2; // Each tick represents 2 seconds
  const hours = 15 + Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
}

/**
 * Master simulation step function
 */
export function stepSimulation(world: SimulationWorld): SimulationWorld {
  const newTick = world.tick + 1;
  const timestamp = formatSimTimestamp(newTick);
  const newEvents: SimulationEvent[] = [];

  // Deep copy / clone state for immutability
  const teams = {
    alpha: { ...world.teams.alpha, completedRoute: [...world.teams.alpha.completedRoute] },
    bravo: { ...world.teams.bravo, completedRoute: [...world.teams.bravo.completedRoute] }
  };
  const civilians: CivilianGroup[] = world.civilians.map(c => ({ ...c }));
  const shelter = { ...world.shelter };
  const drone = { ...world.drone, carriedMessages: [...world.drone.carriedMessages] };
  const beliefs = {
    alpha: {
      ...world.beliefs.alpha,
      grid: { ...world.beliefs.alpha.grid },
      knownCivilians: { ...world.beliefs.alpha.knownCivilians },
      knownClaims: { ...world.beliefs.alpha.knownClaims }
    },
    bravo: {
      ...world.beliefs.bravo,
      grid: { ...world.beliefs.bravo.grid },
      knownCivilians: { ...world.beliefs.bravo.knownCivilians },
      knownClaims: { ...world.beliefs.bravo.knownClaims }
    }
  };

  // 1. SENSING PHASE (Local observations only)
  const scanAlpha = scanSurroundings(teams.alpha, world.cells, civilians, shelter, newTick);
  const alphaBeliefRes = applyObservationsToBelief(beliefs.alpha, scanAlpha.observations, newTick);
  updateKnownCivilianMetadata(beliefs.alpha, scanAlpha.detectedCivilians, teams.alpha.teamId, newTick);

  if (alphaBeliefRes.newCivilianDiscovered) {
    for (const c of scanAlpha.detectedCivilians) {
      newEvents.push({
        id: `ev_disc_a_${newTick}_${c.groupId}`,
        tick: newTick,
        timestamp,
        category: 'rescue',
        severity: 'info',
        title: 'Team Alpha Discovered Civilians',
        description: `Visual confirmation of ${c.name} (${c.size} people) at (${c.position.x},${c.position.y}).`
      });
    }
  }

  const scanBravo = scanSurroundings(teams.bravo, world.cells, civilians, shelter, newTick);
  const bravoBeliefRes = applyObservationsToBelief(beliefs.bravo, scanBravo.observations, newTick);
  updateKnownCivilianMetadata(beliefs.bravo, scanBravo.detectedCivilians, teams.bravo.teamId, newTick);

  if (bravoBeliefRes.newCivilianDiscovered) {
    for (const c of scanBravo.detectedCivilians) {
      newEvents.push({
        id: `ev_disc_b_${newTick}_${c.groupId}`,
        tick: newTick,
        timestamp,
        category: 'rescue',
        severity: 'info',
        title: 'Team Bravo Discovered Civilians',
        description: `Visual confirmation of ${c.name} (${c.size} people) at (${c.position.x},${c.position.y}).`
      });
    }
  }

  // Queue outgoing observation packets for transmission
  if (scanAlpha.observations.length > 0) {
    queueOutgoingMessage(
      teams.alpha,
      'neighbourhood_bravo',
      'observation',
      { observations: scanAlpha.observations },
      newTick
    );
  }
  if (scanBravo.observations.length > 0) {
    queueOutgoingMessage(
      teams.bravo,
      'neighbourhood_alpha',
      'observation',
      { observations: scanBravo.observations },
      newTick
    );
  }

  // 2. COMMUNICATIONS PHASE
  if (world.radioConnected) {
    const radioRes = handleDirectRadioComms(
      true,
      teams.alpha,
      teams.bravo,
      beliefs.alpha,
      beliefs.bravo,
      newTick,
      timestamp
    );
    newEvents.push(...radioRes.events);
  }

  // 3. DRONE COURIER RELAY PHASE
  const droneRes = updateDroneStep(
    drone,
    beliefs.alpha,
    beliefs.bravo,
    teams.alpha.pendingOutgoingMessages,
    teams.bravo.pendingOutgoingMessages,
    newTick,
    timestamp
  );
  newEvents.push(...droneRes.events);

  // 4. AGENT DECISIONS & ACTIONS
  const alphaStep = stepAgent(
    teams.alpha,
    beliefs.alpha,
    civilians,
    shelter,
    world.cells,
    world.radioConnected,
    newTick,
    timestamp
  );
  newEvents.push(...alphaStep.events);

  const bravoStep = stepAgent(
    teams.bravo,
    beliefs.bravo,
    civilians,
    shelter,
    world.cells,
    world.radioConnected,
    newTick,
    timestamp
  );
  newEvents.push(...bravoStep.events);

  // 5. CONFLICT DETECTION & RESOLUTION
  let activeConflicts = 0;
  let resolvedConflicts = world.stats.resolvedConflicts;

  const alphaClaimCiv2 = beliefs.alpha.knownClaims['civ_2'];
  const bravoClaimCiv2 = beliefs.bravo.knownClaims['civ_2'];
  const civ2 = civilians.find(c => c.groupId === 'civ_2');

  if (civ2 && civ2.status !== 'delivered' && detectClaimConflicts(alphaClaimCiv2, bravoClaimCiv2)) {
    if (!world.radioConnected) {
      activeConflicts = 1;
      // If just detected conflict during blackout
      if (world.stats.activeConflicts === 0) {
        newEvents.push({
          id: `ev_conf_${newTick}`,
          tick: newTick,
          timestamp,
          category: 'conflict',
          severity: 'danger',
          title: 'Contested Target Conflict Detected',
          description: `Both Team Alpha and Team Bravo have provisionally targeted ${civ2.name}. Network partition prevents coordination!`
        });
      }
    } else {
      // Reconnected! Resolve immediately!
      const resolutionRes = resolveClaimConflict(
        civ2,
        teams.alpha,
        teams.bravo,
        alphaClaimCiv2!,
        bravoClaimCiv2!,
        newTick,
        timestamp
      );
      newEvents.push(resolutionRes.event);
      resolvedConflicts += 1;

      // Apply resolution to claims
      if (resolutionRes.resolution.winningTeamId === 'team_alpha') {
        alphaClaimCiv2!.status = 'confirmed';
        bravoClaimCiv2!.status = 'rejected';
        beliefs.bravo.knownClaims['civ_2'].status = 'rejected';
        teams.bravo.currentTargetId = undefined;
      } else {
        bravoClaimCiv2!.status = 'confirmed';
        alphaClaimCiv2!.status = 'rejected';
        beliefs.alpha.knownClaims['civ_2'].status = 'rejected';
        teams.alpha.currentTargetId = undefined;
      }
    }
  }

  // 6. AI RECOMMENDATIONS
  const recAlpha = generateTeamRecommendation(
    teams.alpha,
    beliefs.alpha,
    shelter,
    world.radioConnected,
    newTick
  );
  const recBravo = generateTeamRecommendation(
    teams.bravo,
    beliefs.bravo,
    shelter,
    world.radioConnected,
    newTick
  );

  // 7. STATS
  const deliveredCount = civilians
    .filter(c => c.status === 'delivered')
    .reduce((sum, c) => sum + c.size, 0);

  const awaitingCount = world.stats.totalCivilians - deliveredCount;

  return {
    ...world,
    tick: newTick,
    cells: world.cells,
    teams,
    civilians,
    shelter,
    drone,
    beliefs,
    recommendations: {
      alpha: recAlpha,
      bravo: recBravo
    },
    events: [...world.events, ...newEvents].slice(-60), // Keep latest 60 events
    stats: {
      totalCivilians: world.stats.totalCivilians,
      rescuedCivilians: deliveredCount,
      awaitingRescue: awaitingCount,
      activeConflicts,
      resolvedConflicts,
      messagesRelayedByDrone: drone.deliveryHistoryCount
    }
  };
}
