/**
 * Dashboard data contracts. Capacities and rescue totals count people; positions are grid cells
 * and diagnostic delays are seconds.
 */
/** Zero-based cell coordinates; movement uses simulation validation, not pixel positions. */
export interface GridPosition {
  x: number;
  y: number;
}

export type CivilianStatus = 'available' | 'claimed' | 'picked_up' | 'delivered';

/** A whole civilian group and its pickup/delivery ownership. */
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

/** Shelter occupancy and capacity measured in people. */
export interface Shelter {
  shelterId: string;
  name: string;
  position: GridPosition;
  capacity: number;
  occupants: number;
}

export type AgentState = 'idle' | 'moving' | 'rescuing' | 'delivering' | 'waiting';

/** A team snapshot; a nonempty passenger load remains busy until shelter delivery. */
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

/** One cell fact with its original observation tick and observer. */
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

/** Only knowledge available to this team, including packets actually received. */
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

/** A versionless browser-demo reservation; the live backend uses its authoritative task ledger. */
export interface TaskClaim {
  claimId: string;
  teamId: string;
  civilianGroupId: string;
  claimedAtTick: number;
  status: 'provisional' | 'confirmed' | 'rejected' | 'completed';
  reason?: string;
}

/** A browser-demo arbitration result for competing claims. */
export interface TaskClaimResolution {
  civilianGroupId: string;
  winningTeamId?: string;
  winningClaimId?: string;
  status: 'confirmed' | 'rejected';
  reason: string;
  resolvedAtTick: number;
}

/** A dashboard transport record; enqueueing a packet does not imply delivery. */
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

/** Sanitized request accounting and wall-clock retry/latency values in seconds. */
export interface AIRequestDiagnostics {
  requests: number;
  succeeded: number;
  failed: number;
  stale: number;
  rejected: number;
  categories: Record<string, number>;
  lastError: string | null;
  lastLatencySeconds: number | null;
  retryInSeconds: number;
  timeoutSeconds: number;
  disabled: boolean;
}

/** Actual drone position, mission diagnostics, undelivered messages, and observed coverage. */
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
  reasoning?: string;
  aiModel?: string | null;
  agentSystem?: {
    mission: 'scout' | 'courier' | 'return';
    scout: {
      goal: [number, number] | null; status: string; coveredCells: number;
      totalCells: number; coverageComplete: boolean;
      decisionSource: 'claude' | 'coverage_execution'; diagnostics: AIRequestDiagnostics;
    };
    planner: { priorities: string[]; status: string; diagnostics: AIRequestDiagnostics };
    courier: { targetTeam: string | null; contactRadius: number };
    api: { requests: number; requestLimit: number | null; usage: Record<string, number> };
    queuedTasks: string[];
    assignments: { groupId: string; teamId: string; phase: 'pending_delivery' | 'active'; aiRanked: boolean }[];
  };
}

export type EventSeverity = 'info' | 'warning' | 'danger' | 'success';
export type EventCategory = 'network' | 'team' | 'drone' | 'rescue' | 'ai' | 'conflict';

/** A bounded feed entry identified independently of its story timestamp. */
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

/** The actual plan explanation; confidence is 0-100 and fallback is explicitly labelled. */
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

/** Scenario metadata retained for protocol compatibility, not a rendered radio corridor. */
export interface Neighbourhood {
  id: 'neighbourhood_alpha' | 'neighbourhood_bravo';
  name: string;
  center: GridPosition;
  radius: number;
  bounds: { minX: number; maxX: number; minY: number; maxY: number };
  color: string;
}

/** Authoritative terrain/flood presentation for one cell. */
export interface WorldGridCell {
  x: number;
  y: number;
  isFlooded: boolean;
  waterDepth: number; // 0 = dry, 1 = shallow, 2 = moderate, 3 = deep
  isSubmergedRoad: boolean;
  elevation: number;
}

/** Complete admin-view snapshot; controllers still receive only sensor/report-limited facts. */
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
