export interface GridPosition {
  x: number;
  y: number;
}

export type CivilianStatus = 'available' | 'claimed' | 'picked_up' | 'delivered';

export interface CivilianGroup {
  groupId: string;
  name: string;
  position: GridPosition;
  size: number;
  status: CivilianStatus;
  claimedByTeamId?: string;
  pickedUpByTeamId?: string;
  deliveredToShelterId?: string;
}

export interface Shelter {
  shelterId: string;
  name: string;
  position: GridPosition;
  capacity: number;
  occupants: number;
}

export type AgentState = 'idle' | 'moving' | 'rescuing' | 'delivering' | 'waiting';

export interface RescueTeam {
  teamId: string;
  name: string;
  callsign: 'Alpha' | 'Bravo';
  color: string;
  position: GridPosition;
  direction: 'N' | 'S' | 'E' | 'W' | 'IDLE';
  state: AgentState;
  capacity: number;
  carriedCivilians: number;
  carriedGroupIds: string[];
  neighbourhoodId: 'neighbourhood_alpha' | 'neighbourhood_bravo';
  currentTargetId?: string;
  plannedRoute: GridPosition[];
  completedRoute: GridPosition[];
  lastCommTick: number;
  pendingOutgoingMessages: Message[];
}

export type CellBeliefState = 'unknown' | 'safe' | 'flooded' | 'civilian' | 'shelter';

export interface CellObservation {
  x: number;
  y: number;
  state: CellBeliefState;
  waterDepth?: number; // 0 to 3
  civilianGroupId?: string;
  civilianStatus?: CivilianStatus;
  observedAtTick: number;
  observerId: string;
}

export interface TeamBeliefMap {
  teamId: string;
  version: number;
  grid: Record<string, CellObservation>; // key = `${x},${y}`
  knownCivilians: Record<string, {
    groupId: string;
    position: GridPosition;
    size: number;
    status: CivilianStatus;
    claimedBy?: string;
    observedTick: number;
    observerId: string;
  }>;
  knownClaims: Record<string, TaskClaim>; // key = groupId
  lastUpdatedTick: number;
}

export interface TaskClaim {
  claimId: string;
  teamId: string;
  civilianGroupId: string;
  claimedAtTick: number;
  status: 'provisional' | 'confirmed' | 'rejected' | 'completed';
  reason?: string;
}

export interface TaskClaimResolution {
  civilianGroupId: string;
  winningTeamId?: string;
  winningClaimId?: string;
  status: 'confirmed' | 'rejected';
  reason: string;
  resolvedAtTick: number;
}

export interface Message {
  messageId: string;
  senderId: string;
  originNeighbourhood: string;
  destinationNeighbourhood: string;
  type: 'observation' | 'task_claim' | 'belief_sync' | 'status_update';
  createdTick: number;
  data: {
    observations?: CellObservation[];
    claim?: TaskClaim;
    civilianUpdate?: {
      groupId: string;
      status: CivilianStatus;
      teamId: string;
    };
  };
}

export type DroneStatus = 'idle' | 'flying' | 'delivering' | 'returning' | 'paused';

export interface DroneState {
  droneId: string;
  name: string;
  position: GridPosition;
  subPosition?: { x: number; y: number }; // For smooth interpolation between grid cells
  status: DroneStatus;
  enabled: boolean;
  speed: number;
  currentLegIndex: number;
  routeWaypoints: GridPosition[];
  destinationNeighbourhood: string;
  carriedMessages: Message[];
  deliveryHistoryCount: number;
  lastDeliveryTick?: number;
}

export type EventSeverity = 'info' | 'warning' | 'danger' | 'success';
export type EventCategory = 'network' | 'team' | 'drone' | 'rescue' | 'ai' | 'conflict';

export interface SimulationEvent {
  id: string;
  tick: number;
  timestamp: string;
  category: EventCategory;
  severity: EventSeverity;
  title: string;
  description: string;
  teamId?: string;
}

export interface AIRecommendation {
  teamId: string;
  recommendedTargetId?: string;
  targetDescription: string;
  recommendedAction: string;
  reasoning: string;
  confidence: number; // 0 to 100
  missingInformation: string;
  isAiFallback: boolean; // True when radio disconnected and using fallback rule
  generatedTick: number;
}

export interface Neighbourhood {
  id: 'neighbourhood_alpha' | 'neighbourhood_bravo';
  name: string;
  center: GridPosition;
  radius: number;
  bounds: { minX: number; maxX: number; minY: number; maxY: number };
  color: string;
}

export interface WorldGridCell {
  x: number;
  y: number;
  isFlooded: boolean;
  waterDepth: number; // 0 = dry, 1 = shallow, 2 = moderate, 3 = deep
  isSubmergedRoad: boolean;
  elevation: number;
}

export interface SimulationWorld {
  tick: number;
  width: number;
  height: number;
  cells: WorldGridCell[][];
  neighbourhoods: {
    alpha: Neighbourhood;
    bravo: Neighbourhood;
  };
  radioConnected: boolean;
  teams: {
    alpha: RescueTeam;
    bravo: RescueTeam;
  };
  civilians: CivilianGroup[];
  shelter: Shelter;
  drone: DroneState;
  beliefs: {
    alpha: TeamBeliefMap;
    bravo: TeamBeliefMap;
  };
  recommendations: {
    alpha: AIRecommendation;
    bravo: AIRecommendation;
  };
  events: SimulationEvent[];
  stats: {
    totalCivilians: number;
    rescuedCivilians: number;
    awaitingRescue: number;
    activeConflicts: number;
    resolvedConflicts: number;
    messagesRelayedByDrone: number;
  };
}
