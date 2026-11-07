/**
 * Browser demo claim arbitration with deterministic distance/team tie-breaking and explicit
 * event reporting.
 */
import {
  CivilianGroup,
  RescueTeam,
  SimulationEvent,
  TaskClaim,
  TaskClaimResolution
} from '../types/simulation';

/**
 * Detect if both teams have active claims on the same civilian group
 */
export function detectClaimConflicts(
  alphaClaim?: TaskClaim,
  bravoClaim?: TaskClaim
): boolean {
  if (!alphaClaim || !bravoClaim) return false;
  if (alphaClaim.status === 'rejected' || bravoClaim.status === 'rejected') return false;
  if (alphaClaim.status === 'completed' || bravoClaim.status === 'completed') return false;

  return alphaClaim.civilianGroupId === bravoClaim.civilianGroupId;
}

/**
 * Deterministically resolve conflicting claims when radio reconnects
 */
export function resolveClaimConflict(
  group: CivilianGroup,
  alphaTeam: RescueTeam,
  bravoTeam: RescueTeam,
  alphaClaim: TaskClaim,
  bravoClaim: TaskClaim,
  currentTick: number,
  timestamp: string
): {
  resolution: TaskClaimResolution;
  event: SimulationEvent;
} {
  // 1. Authoritative check: if already picked up or delivered, winner is the team that picked them up
  if (group.pickedUpByTeamId === 'team_alpha') {
    return {
      resolution: {
        civilianGroupId: group.groupId,
        winningTeamId: 'team_alpha',
        winningClaimId: alphaClaim.claimId,
        status: 'confirmed',
        reason: 'Team Alpha already initiated physical rescue/pickup.',
        resolvedAtTick: currentTick
      },
      event: {
        id: `ev_res_${currentTick}_${Date.now()}`,
        tick: currentTick,
        timestamp,
        category: 'conflict',
        severity: 'info',
        title: 'Conflict Resolved (In Progress)',
        description: `Contested claim on ${group.name} confirmed for Team Alpha: unit has already secured evacuees.`
      }
    };
  }

  if (group.pickedUpByTeamId === 'team_bravo') {
    return {
      resolution: {
        civilianGroupId: group.groupId,
        winningTeamId: 'team_bravo',
        winningClaimId: bravoClaim.claimId,
        status: 'confirmed',
        reason: 'Team Bravo already initiated physical rescue/pickup.',
        resolvedAtTick: currentTick
      },
      event: {
        id: `ev_res_${currentTick}_${Date.now()}`,
        tick: currentTick,
        timestamp,
        category: 'conflict',
        severity: 'info',
        title: 'Conflict Resolved (In Progress)',
        description: `Contested claim on ${group.name} confirmed for Team Bravo: unit has already secured evacuees.`
      }
    };
  }

  // 2. Tie-break by distance to target
  const distAlpha = Math.hypot(
    alphaTeam.position.x - group.position.x,
    alphaTeam.position.y - group.position.y
  );
  const distBravo = Math.hypot(
    bravoTeam.position.x - group.position.x,
    bravoTeam.position.y - group.position.y
  );

  let winningTeamId: string;
  let winningClaimId: string;
  let reason: string;

  if (Math.abs(distAlpha - distBravo) > 0.1) {
    if (distAlpha < distBravo) {
      winningTeamId = 'team_alpha';
      winningClaimId = alphaClaim.claimId;
      reason = `Team Alpha is closer (${distAlpha.toFixed(1)} cells vs ${distBravo.toFixed(1)} cells).`;
    } else {
      winningTeamId = 'team_bravo';
      winningClaimId = bravoClaim.claimId;
      reason = `Team Bravo is closer (${distBravo.toFixed(1)} cells vs ${distAlpha.toFixed(1)} cells).`;
    }
  } else {
    // If distance tied, earlier claim tick wins
    if (alphaClaim.claimedAtTick <= bravoClaim.claimedAtTick) {
      winningTeamId = 'team_alpha';
      winningClaimId = alphaClaim.claimId;
      reason = `Team Alpha claimed earlier (tick ${alphaClaim.claimedAtTick} vs ${bravoClaim.claimedAtTick}).`;
    } else {
      winningTeamId = 'team_bravo';
      winningClaimId = bravoClaim.claimId;
      reason = `Team Bravo claimed earlier (tick ${bravoClaim.claimedAtTick} vs ${alphaClaim.claimedAtTick}).`;
    }
  }

  const winningTeamName = winningTeamId === 'team_alpha' ? 'Team Alpha' : 'Team Bravo';
  const losingTeamName = winningTeamId === 'team_alpha' ? 'Team Bravo' : 'Team Alpha';

  return {
    resolution: {
      civilianGroupId: group.groupId,
      winningTeamId,
      winningClaimId,
      status: 'confirmed',
      reason,
      resolvedAtTick: currentTick
    },
    event: {
      id: `ev_res_${currentTick}_${Date.now()}`,
      tick: currentTick,
      timestamp,
      category: 'conflict',
      severity: 'warning',
      title: 'Conflicting Claims Resolved',
      description: `Both teams claimed ${group.name}. Deterministic arbitration assigned target to ${winningTeamName} (${reason}). ${losingTeamName} stood down.`
    }
  };
}
