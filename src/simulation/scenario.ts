/**
 * Construct the browser-only starting scenario and isolated local belief maps when the Python
 * backend is unavailable.
 */
import {
  CivilianGroup,
  DroneState,
  GridPosition,
  RescueTeam,
  Shelter,
  SimulationWorld,
  TeamBeliefMap,
  WorldGridCell,
  Neighbourhood,
  AIRecommendation
} from '../types/simulation';

export function createInitialScenario(): SimulationWorld {
  const width = 20;
  const height = 20;

  // Build 20x20 grid with realistic flooded zones, submerged roads, and dry high ground
  const cells: WorldGridCell[][] = [];

  for (let y = 0; y < height; y++) {
    const row: WorldGridCell[] = [];
    for (let x = 0; x < width; x++) {
      // Natural flood river & low elevation basin splitting the map around x = 9-11
      // and southern runoff
      let isFlooded = false;
      let waterDepth = 0;
      let isSubmergedRoad = false;

      // Central river / surge canal
      const riverDist = Math.abs(x - (9 + Math.sin(y / 2.5) * 2));
      const southernBasin = y > 15 && x > 6 && x < 14;

      if (riverDist < 1.4 || southernBasin) {
        isFlooded = true;
        waterDepth = 3; // Deep impassable water
      } else if (riverDist < 2.5) {
        isFlooded = true;
        waterDepth = 2; // Moderate water
      } else if (riverDist < 3.2 || (y > 12 && x > 8 && x < 13)) {
        isFlooded = true;
        waterDepth = 1; // Shallow flood
      }

      // Predefined urban road network
      const isEastWestAvenue = y === 4 || y === 10 || y === 16;
      const isNorthSouthRoad = x === 4 || x === 9 || x === 15;

      if ((isEastWestAvenue || isNorthSouthRoad) && isFlooded) {
        isSubmergedRoad = true;
        // Submerged roads are passable shallow water
        if (waterDepth > 2) waterDepth = 2;
      }

      // Shelter hill (around x=9, y=2) is dry high ground
      if (Math.hypot(x - 9, y - 2) < 2.2) {
        isFlooded = false;
        waterDepth = 0;
        isSubmergedRoad = false;
      }

      // Base camps are dry
      if (Math.hypot(x - 2, y - 3) < 2 || Math.hypot(x - 17, y - 17) < 2) {
        isFlooded = false;
        waterDepth = 0;
      }

      row.push({
        x,
        y,
        isFlooded,
        waterDepth,
        isSubmergedRoad,
        elevation: isFlooded ? Math.max(1, 4 - waterDepth) : 5
      });
    }
    cells.push(row);
  }

  const neighbourhoods: { alpha: Neighbourhood; bravo: Neighbourhood } = {
    alpha: {
      id: 'neighbourhood_alpha',
      name: 'Alpha Tactical Sector (West)',
      center: { x: 4, y: 6 },
      radius: 6.5,
      bounds: { minX: 0, maxX: 8, minY: 0, maxY: 19 },
      color: '#38bdf8'
    },
    bravo: {
      id: 'neighbourhood_bravo',
      name: 'Bravo Tactical Sector (East)',
      center: { x: 15, y: 13 },
      radius: 6.5,
      bounds: { minX: 11, maxX: 19, minY: 0, maxY: 19 },
      color: '#22c55e'
    }
  };

  const civilians: CivilianGroup[] = [
    {
      groupId: 'civ_1',
      name: 'Civilians #1 (West School)',
      position: { x: 3, y: 9 },
      size: 4,
      status: 'available'
    },
    {
      groupId: 'civ_2',
      name: 'Civilians #2 (Border Clinic)',
      position: { x: 10, y: 10 }, // Contested central border location!
      size: 3,
      status: 'available'
    },
    {
      groupId: 'civ_3',
      name: 'Civilians #3 (East Depot)',
      position: { x: 16, y: 11 },
      size: 5,
      status: 'available'
    }
  ];

  const shelter: Shelter = {
    shelterId: 'shelter_north',
    name: 'Northern Municipal Shelter',
    position: { x: 9, y: 2 },
    capacity: 25,
    occupants: 0
  };

  const teamAlpha: RescueTeam = {
    teamId: 'team_alpha',
    name: 'Rescue Team Alpha',
    callsign: 'Alpha',
    color: '#38bdf8',
    position: { x: 2, y: 3 },
    direction: 'S',
    state: 'idle',
    capacity: 5,
    carriedCivilians: 0,
    carriedGroupIds: [],
    neighbourhoodId: 'neighbourhood_alpha',
    plannedRoute: [],
    completedRoute: [{ x: 2, y: 3 }],
    lastCommTick: 0,
    pendingOutgoingMessages: []
  };

  const teamBravo: RescueTeam = {
    teamId: 'team_bravo',
    name: 'Rescue Team Bravo',
    callsign: 'Bravo',
    color: '#22c55e',
    position: { x: 17, y: 17 },
    direction: 'N',
    state: 'idle',
    capacity: 5,
    carriedCivilians: 0,
    carriedGroupIds: [],
    neighbourhoodId: 'neighbourhood_bravo',
    plannedRoute: [],
    completedRoute: [{ x: 17, y: 17 }],
    lastCommTick: 0,
    pendingOutgoingMessages: []
  };

  // Fixed courier drone route between Alpha Hub (4, 6) and Bravo Hub (15, 13)
  const droneRoute: GridPosition[] = [
    { x: 4, y: 6 },
    { x: 6, y: 5 },
    { x: 8, y: 6 },
    { x: 10, y: 8 },
    { x: 12, y: 10 },
    { x: 14, y: 12 },
    { x: 15, y: 13 },
    // Return path
    { x: 14, y: 12 },
    { x: 12, y: 10 },
    { x: 10, y: 8 },
    { x: 8, y: 6 },
    { x: 6, y: 5 }
  ];

  const drone: DroneState = {
    droneId: 'drone_courier_01',
    name: 'AeroRelay Drone CR-1',
    position: { x: 4, y: 6 },
    subPosition: { x: 4, y: 6 },
    status: 'idle',
    enabled: true,
    speed: 1,
    currentLegIndex: 0,
    routeWaypoints: droneRoute,
    destinationNeighbourhood: 'neighbourhood_bravo',
    carriedMessages: [],
    deliveryHistoryCount: 0
  };

  // Build initial local belief maps
  // Each team initially only knows about its own base and shelter location
  const beliefs: { alpha: TeamBeliefMap; bravo: TeamBeliefMap } = {
    alpha: createInitialBeliefMap('team_alpha', teamAlpha.position, shelter),
    bravo: createInitialBeliefMap('team_bravo', teamBravo.position, shelter)
  };

  const initialRecommendations: { alpha: AIRecommendation; bravo: AIRecommendation } = {
    alpha: {
      teamId: 'team_alpha',
      recommendedTargetId: undefined,
      targetDescription: 'Initialising Area Scan',
      recommendedAction: 'Scan Sector West',
      reasoning: 'Reconnaissance of western zone underway. Establishing sensor baseline.',
      confidence: 88,
      missingInformation: 'Central border and eastern sectors unobserved.',
      isAiFallback: false,
      generatedTick: 0
    },
    bravo: {
      teamId: 'team_bravo',
      recommendedTargetId: undefined,
      targetDescription: 'Initialising Area Scan',
      recommendedAction: 'Scan Sector East',
      reasoning: 'Reconnaissance of eastern sector active. Ready for dispatch.',
      confidence: 85,
      missingInformation: 'Western and border sectors unobserved.',
      isAiFallback: false,
      generatedTick: 0
    }
  };

  return {
    tick: 0,
    width,
    height,
    cells,
    neighbourhoods,
    radioConnected: true,
    teams: {
      alpha: teamAlpha,
      bravo: teamBravo
    },
    civilians,
    shelter,
    drone,
    beliefs,
    recommendations: initialRecommendations,
    events: [
      {
        id: 'ev_init_1',
        tick: 0,
        timestamp: '15:00:00',
        category: 'network',
        severity: 'info',
        title: 'Simulation Initialised',
        description: 'Command centre online. Radio link between Alpha and Bravo is ACTIVE.'
      },
      {
        id: 'ev_init_2',
        tick: 0,
        timestamp: '15:00:01',
        category: 'team',
        severity: 'info',
        title: 'Rescue Units Deployed',
        description: 'Alpha deployed at (2,3), Bravo deployed at (17,17). Courier drone stationed at Alpha hub.'
      }
    ],
    stats: {
      totalCivilians: 12,
      rescuedCivilians: 0,
      awaitingRescue: 12,
      activeConflicts: 0,
      resolvedConflicts: 0,
      messagesRelayedByDrone: 0
    }
  };
}

/** Seed one team's browser-demo observations without sharing another team's private grid. */
function createInitialBeliefMap(
  teamId: string,
  startPos: GridPosition,
  shelter: Shelter
): TeamBeliefMap {
  const grid: Record<string, any> = {};
  const knownCivilians: Record<string, any> = {};

  // Initially mark the shelter as known safe
  grid[`${shelter.position.x},${shelter.position.y}`] = {
    x: shelter.position.x,
    y: shelter.position.y,
    state: 'shelter',
    waterDepth: 0,
    observedAtTick: 0,
    observerId: 'system_initial'
  };

  // Initially observe small radius around starting position
  for (let dy = -2; dy <= 2; dy++) {
    for (let dx = -2; dx <= 2; dx++) {
      const x = startPos.x + dx;
      const y = startPos.y + dy;
      if (x >= 0 && x < 20 && y >= 0 && y < 20) {
        grid[`${x},${y}`] = {
          x,
          y,
          state: 'safe',
          waterDepth: 0,
          observedAtTick: 0,
          observerId: teamId
        };
      }
    }
  }

  // Pre-seed known emergency 911 distress reports per sector
  if (teamId === 'team_alpha') {
    knownCivilians['civ_1'] = {
      groupId: 'civ_1',
      position: { x: 3, y: 9 },
      size: 4,
      status: 'available',
      observedTick: 0,
      observerId: 'emergency_dispatch'
    };
    knownCivilians['civ_2'] = {
      groupId: 'civ_2',
      position: { x: 10, y: 10 },
      size: 3,
      status: 'available',
      observedTick: 0,
      observerId: 'emergency_dispatch'
    };
  } else {
    knownCivilians['civ_3'] = {
      groupId: 'civ_3',
      position: { x: 16, y: 11 },
      size: 5,
      status: 'available',
      observedTick: 0,
      observerId: 'emergency_dispatch'
    };
    knownCivilians['civ_2'] = {
      groupId: 'civ_2',
      position: { x: 10, y: 10 },
      size: 3,
      status: 'available',
      observedTick: 0,
      observerId: 'emergency_dispatch'
    };
  }

  return {
    teamId,
    version: 1,
    grid,
    knownCivilians,
    knownClaims: {},
    lastUpdatedTick: 0
  };
}
