/**
 * Browser demo radio exchange and queued courier packets; transport delivery remains separate
 * from world mutation.
 */
import {
  CellObservation,
  CivilianGroup,
  Message,
  RescueTeam,
  SimulationEvent,
  TaskClaim,
  TeamBeliefMap
} from '../types/simulation';
import { applyObservationsToBelief } from './beliefs';

export function handleDirectRadioComms(
  radioConnected: boolean,
  teamAlpha: RescueTeam,
  teamBravo: RescueTeam,
  beliefAlpha: TeamBeliefMap,
  beliefBravo: TeamBeliefMap,
  currentTick: number,
  timestamp: string
): { events: SimulationEvent[]; syncOccurred: boolean } {
  const events: SimulationEvent[] = [];
  let syncOccurred = false;

  if (!radioConnected) {
    return { events, syncOccurred: false };
  }

  // Radio is connected: flush any pending messages directly
  if (teamAlpha.pendingOutgoingMessages.length > 0) {
    const msgs = [...teamAlpha.pendingOutgoingMessages];
    teamAlpha.pendingOutgoingMessages = [];

    for (const msg of msgs) {
      if (msg.data.observations) {
        applyObservationsToBelief(beliefBravo, msg.data.observations, currentTick);
      }
    }
    syncOccurred = true;
  }

  if (teamBravo.pendingOutgoingMessages.length > 0) {
    const msgs = [...teamBravo.pendingOutgoingMessages];
    teamBravo.pendingOutgoingMessages = [];

    for (const msg of msgs) {
      if (msg.data.observations) {
        applyObservationsToBelief(beliefAlpha, msg.data.observations, currentTick);
      }
    }
    syncOccurred = true;
  }

  return { events, syncOccurred };
}

/**
 * Queue an outgoing observation packet from a team
 */
export function queueOutgoingMessage(
  team: RescueTeam,
  destinationNeighbourhood: string,
  type: Message['type'],
  data: Message['data'],
  currentTick: number
) {
  const msg: Message = {
    messageId: `msg_${team.teamId}_${currentTick}_${Math.random().toString(36).slice(2, 7)}`,
    senderId: team.teamId,
    originNeighbourhood: team.neighbourhoodId,
    destinationNeighbourhood,
    type,
    createdTick: currentTick,
    data
  };

  team.pendingOutgoingMessages.push(msg);
}
