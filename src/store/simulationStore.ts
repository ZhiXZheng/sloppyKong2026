/**
 * Central dashboard state and operator actions. Python owns live simulation truth; failed live
 * steps pause playback rather than inventing local progress.
 */
import { create } from 'zustand';
import { SimulationWorld } from '../types/simulation';
import { createInitialScenario } from '../simulation/scenario';
import { stepSimulation, formatSimTimestamp } from '../simulation/engine';
import {
  fetchState,
  stepSimulationApi,
  resetSimulationApi,
  toggleRadioApi,
  controlDroneApi
} from '../simulation/pythonClient';

interface SelectedEntity {
  type: 'team' | 'civilian' | 'drone' | 'shelter' | 'cell';
  id?: string;
  x?: number;
  y?: number;
}

interface Overlays {
  flood: boolean;
  routes: boolean;
  civilians: boolean;
}

interface SimulationStore {
  world: SimulationWorld;
  isRunning: boolean;
  speed: 1 | 2 | 4;
  selectedEntity: SelectedEntity | null;
  overlays: Overlays;
  isPythonBackendConnected: boolean;

  // Actions
  init: () => Promise<void>;
  startSimulation: () => void;
  pauseSimulation: () => void;
  togglePlayPause: () => void;
  stepTick: () => Promise<void>;
  resetSimulation: (scenario?: string) => Promise<void>;
  setSpeed: (speed: 1 | 2 | 4) => void;
  toggleRadio: () => Promise<void>;
  launchDrone: () => Promise<void>;
  pauseDrone: () => Promise<void>;
  returnDrone: () => Promise<void>;
  selectEntity: (entity: SelectedEntity | null) => void;
  toggleOverlay: (key: keyof Overlays) => void;
  runPresetScenario: (step: 'normal' | 'partition' | 'droneRelay' | 'reconnect') => void;
}

let stepInFlight = false;

export const useSimulationStore = create<SimulationStore>((set, get) => ({
  world: createInitialScenario(),
  isRunning: false,
  speed: 1,
  selectedEntity: null,
  overlays: {
    flood: true,
    routes: true,
    civilians: true
  },
  isPythonBackendConnected: false,

  // Try Python once on mount; retain the separate browser demo if no backend is reachable.
  init: async () => {
    try {
      const state = await fetchState();
      set({ world: state, isPythonBackendConnected: true });
    } catch (e) {
      console.warn('Python simulation backend offline, using fallback client simulation.', e);
      set({ isPythonBackendConnected: false });
    }
  },

  // Start scheduling ticks without directly mutating the current world.
  startSimulation: () => set({ isRunning: true }),
  // Stop scheduled ticks while retaining all mission state.
  pauseSimulation: () => set({ isRunning: false }),
  // Toggle only the playback scheduler.
  togglePlayPause: () => set(state => ({ isRunning: !state.isRunning })),

  // Prevent overlapping timer requests and pause if an authoritative live step fails.
  stepTick: async () => {
    if (stepInFlight) return;
    const { isPythonBackendConnected } = get();
    if (isPythonBackendConnected) {
      stepInFlight = true;
      try {
        const nextState = await stepSimulationApi();
        set({ world: nextState });
        return;
      } catch (err) {
        console.error('Python step failed; simulation paused:', err);
        set({ isRunning: false });
        return;
      } finally {
        stepInFlight = false;
      }
    }
    // Fallback deterministic stepping
    set(state => ({
      world: stepSimulation(state.world)
    }));
  },

  // Reset server state when connected and clear stale selections and playback.
  resetSimulation: async (scenario: string = 'small') => {
    const { isPythonBackendConnected } = get();
    if (isPythonBackendConnected) {
      try {
        const nextState = await resetSimulationApi(scenario);
        set({
          world: nextState,
          isRunning: false,
          selectedEntity: null
        });
        return;
      } catch (err) {
        console.warn('Python reset failed, using client reset:', err);
      }
    }
    set({
      world: createInitialScenario(),
      isRunning: false,
      selectedEntity: null
    });
  },

  // Choose the existing 1x, 2x, or 4x playback multiplier.
  setSpeed: (speed: 1 | 2 | 4) => set({ speed }),

  // Request a real connectivity change; view overlays never affect communication.
  toggleRadio: async () => {
    const { isPythonBackendConnected, world } = get();
    const nextRadio = !world.radioConnected;

    if (isPythonBackendConnected) {
      try {
        const nextState = await toggleRadioApi(nextRadio);
        set({ world: nextState });
        return;
      } catch (err) {
        console.warn('Python toggleRadio failed, using client logic:', err);
      }
    }

    set(state => {
      const tick = state.world.tick;
      const timestamp = formatSimTimestamp(tick);
      const event = nextRadio
        ? {
            id: `ev_radio_on_${tick}_${Date.now()}`,
            tick,
            timestamp,
            category: 'network' as const,
            severity: 'success' as const,
            title: 'Radio Link Restored',
            description: 'Direct tactical radio link between Alpha and Bravo re-established. Synchronising local observations and claims.'
          }
        : {
            id: `ev_radio_off_${tick}_${Date.now()}`,
            tick,
            timestamp,
            category: 'network' as const,
            severity: 'danger' as const,
            title: 'NETWORK PARTITION WARNING',
            description: 'Radio connection between Alpha and Bravo SEVERED! Units operating independently with divergent belief maps.'
          };

      return {
        world: {
          ...state.world,
          radioConnected: nextRadio,
          events: [...state.world.events, event]
        }
      };
    });
  },

  // Resume the backend drone and playback; never silently switch to a fixed client patrol.
  launchDrone: async () => {
    try {
      const world = await controlDroneApi('launch');
      set({ world, isRunning: true, isPythonBackendConnected: true });
    } catch (err) {
      console.error('Drone launch requires the Python AI backend:', err);
      set({ isRunning: false });
    }
  },

  // Pause drone flight on the backend while preserving accepted team rescue orders.
  pauseDrone: async () => {
    try {
      const world = await controlDroneApi('pause');
      set({ world });
    } catch (err) {
      console.error('Drone pause failed:', err);
      set({ isRunning: false });
    }
  },

  // Send the operator return command and let the backend validate the route.
  returnDrone: async () => {
    try {
      const world = await controlDroneApi('return');
      set({ world, isRunning: true, isPythonBackendConnected: true });
    } catch (err) {
      console.error('Drone return failed:', err);
      set({ isRunning: false });
    }
  },

  // Change the inspected entity without influencing autonomous decisions.
  selectEntity: entity => set({ selectedEntity: entity }),

  // Change only map presentation.
  toggleOverlay: key =>
    set(state => ({
      overlays: {
        ...state.overlays,
        [key]: !state.overlays[key]
      }
    })),

  // Translate scenario shortcuts into the same reset, radio, and launch actions.
  runPresetScenario: preset => {
    const { toggleRadio, launchDrone, resetSimulation } = get();
    if (preset === 'normal') {
      resetSimulation();
    } else if (preset === 'partition') {
      const { world } = get();
      if (world.radioConnected) {
        toggleRadio();
      }
    } else if (preset === 'droneRelay') {
      launchDrone();
    } else if (preset === 'reconnect') {
      const { world } = get();
      if (!world.radioConnected) {
        toggleRadio();
      }
    }
  }
}));
