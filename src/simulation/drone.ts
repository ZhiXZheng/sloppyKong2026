/**
 * Legacy browser-only courier shuttle. The live dashboard uses the Python multi-agent drone
 * system.
 */
import {
  DroneState,
  GridPosition,
  Message,
  SimulationEvent,
  TeamBeliefMap
} from '../types/simulation';
import { applyObservationsToBelief } from './beliefs';

/** Advance the standalone browser courier and apply packets only on arrival at the destination depot. */
export function updateDroneStep(
  drone: DroneState,
  alphaBelief: TeamBeliefMap,
  bravoBelief: TeamBeliefMap,
  alphaPendingMessages: Message[],
  bravoPendingMessages: Message[],
  currentTick: number,
  timestamp: string
): {
  deliveredMessages: Message[];
  events: SimulationEvent[];
  beliefUpdated: 'alpha' | 'bravo' | null;
} {
  const events: SimulationEvent[] = [];
  const deliveredMessages: Message[] = [];
  let beliefUpdated: 'alpha' | 'bravo' | null = null;

  if (!drone.enabled || drone.status === 'paused' || drone.status === 'idle') {
    return { deliveredMessages, events, beliefUpdated };
  }

  const waypoints = drone.routeWaypoints;
  if (!waypoints || waypoints.length === 0) {
    return { deliveredMessages, events, beliefUpdated };
  }

  // Advance along waypoints
  const nextIndex = (drone.currentLegIndex + 1) % waypoints.length;
  drone.currentLegIndex = nextIndex;
  drone.position = waypoints[nextIndex];
  drone.subPosition = { ...waypoints[nextIndex] };

  // Check if at Alpha hub (index 0)
  if (drone.currentLegIndex === 0) {
    // Delivered to Alpha if carrying messages destined for Alpha
    const toAlpha = drone.carriedMessages.filter(
      m => m.destinationNeighbourhood === 'neighbourhood_alpha'
    );

    if (toAlpha.length > 0) {
      deliveredMessages.push(...toAlpha);
      drone.carriedMessages = drone.carriedMessages.filter(
        m => m.destinationNeighbourhood !== 'neighbourhood_alpha'
      );
      drone.deliveryHistoryCount += toAlpha.length;
      drone.lastDeliveryTick = currentTick;

      // Apply delivered observations to Alpha belief map
      for (const msg of toAlpha) {
        if (msg.data.observations) {
          applyObservationsToBelief(alphaBelief, msg.data.observations, currentTick);
        }
      }
      beliefUpdated = 'alpha';

      events.push({
        id: `ev_drone_del_a_${currentTick}`,
        tick: currentTick,
        timestamp,
        category: 'drone',
        severity: 'success',
        title: 'Drone Intelligence Delivered (Alpha)',
        description: `CR-1 arrived at Alpha Hub. Unloaded ${toAlpha.length} packets. Team Alpha belief map updated with eastern intelligence.`
      });
    }

    // Pickup outgoing messages from Alpha to Bravo
    if (alphaPendingMessages.length > 0) {
      const pickedUp = [...alphaPendingMessages];
      drone.carriedMessages.push(...pickedUp);
      alphaPendingMessages.length = 0; // clear queue

      events.push({
        id: `ev_drone_pickup_a_${currentTick}`,
        tick: currentTick,
        timestamp,
        category: 'drone',
        severity: 'info',
        title: 'Drone Messages Collected (Alpha)',
        description: `CR-1 loaded ${pickedUp.length} outgoing tactical messages from Alpha sector.`
      });
    }

    drone.destinationNeighbourhood = 'neighbourhood_bravo';
    drone.status = 'flying';
  }

  // Check if at Bravo hub (index 6 - midpoint of route loop)
  const bravoIndex = 6;
  if (drone.currentLegIndex === bravoIndex) {
    // Delivered to Bravo
    const toBravo = drone.carriedMessages.filter(
      m => m.destinationNeighbourhood === 'neighbourhood_bravo'
    );

    if (toBravo.length > 0) {
      deliveredMessages.push(...toBravo);
      drone.carriedMessages = drone.carriedMessages.filter(
        m => m.destinationNeighbourhood !== 'neighbourhood_bravo'
      );
      drone.deliveryHistoryCount += toBravo.length;
      drone.lastDeliveryTick = currentTick;

      // Apply delivered observations to Bravo belief map
      for (const msg of toBravo) {
        if (msg.data.observations) {
          applyObservationsToBelief(bravoBelief, msg.data.observations, currentTick);
        }
      }
      beliefUpdated = 'bravo';

      events.push({
        id: `ev_drone_del_b_${currentTick}`,
        tick: currentTick,
        timestamp,
        category: 'drone',
        severity: 'success',
        title: 'Drone Intelligence Delivered (Bravo)',
        description: `CR-1 arrived at Bravo Hub. Delivered ${toBravo.length} packets across the partition. Team Bravo belief map updated.`
      });
    }

    // Pickup outgoing messages from Bravo to Alpha
    if (bravoPendingMessages.length > 0) {
      const pickedUp = [...bravoPendingMessages];
      drone.carriedMessages.push(...pickedUp);
      bravoPendingMessages.length = 0; // clear

      events.push({
        id: `ev_drone_pickup_b_${currentTick}`,
        tick: currentTick,
        timestamp,
        category: 'drone',
        severity: 'info',
        title: 'Drone Messages Collected (Bravo)',
        description: `CR-1 loaded ${pickedUp.length} tactical status reports from Bravo sector for return relay.`
      });
    }

    drone.destinationNeighbourhood = 'neighbourhood_alpha';
    drone.status = 'returning';
  }

  return { deliveredMessages, events, beliefUpdated };
}
