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
  coverage: boolean;
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
  returnDrone: () => void;
  selectEntity: (entity: SelectedEntity | null) => void;
  toggleOverlay: (key: keyof Overlays) => void;
  runPresetScenario: (step: 'normal' | 'partition' | 'droneRelay' | 'reconnect') => void;
}

export const useSimulationStore = create<SimulationStore>((set, get) => ({
  world: createInitialScenario(),
  isRunning: false,
  speed: 1,
  selectedEntity: null,
  overlays: {
    flood: true,
    coverage: true,
    routes: true,
    civilians: true
  },
  isPythonBackendConnected: false,

  init: async () => {
    try {
      const state = await fetchState();
      set({ world: state, isPythonBackendConnected: true });
    } catch (e) {
      console.warn('Python simulation backend offline, using fallback client simulation.', e);
      set({ isPythonBackendConnected: false });
    }
  },

  startSimulation: () => set({ isRunning: true }),
  pauseSimulation: () => set({ isRunning: false }),
  togglePlayPause: () => set(state => ({ isRunning: !state.isRunning })),

  stepTick: async () => {
    const { isPythonBackendConnected } = get();
    if (isPythonBackendConnected) {
      try {
        const nextState = await stepSimulationApi();
        set({ world: nextState });
        return;
      } catch (err) {
        console.warn('Python step failed, falling back to client logic:', err);
      }
    }
    // Fallback deterministic stepping
    set(state => ({
      world: stepSimulation(state.world)
    }));
  },

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

  setSpeed: (speed: 1 | 2 | 4) => set({ speed }),

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

  launchDrone: async () => {
    const { isPythonBackendConnected } = get();
    if (isPythonBackendConnected) {
      try {
        const nextState = await controlDroneApi('launch');
        set({ world: nextState, isRunning: true });
        return;
      } catch (err) {
        console.warn('Python controlDrone failed:', err);
      }
    }

    set(state => {
      const tick = state.world.tick;
      const timestamp = formatSimTimestamp(tick);
      return {
        isRunning: true,
        world: {
          ...state.world,
          drone: {
            ...state.world.drone,
            enabled: true,
            status: 'flying'
          },
          events: [
            ...state.world.events,
            {
              id: `ev_drone_launch_${tick}`,
              tick,
              timestamp,
              category: 'drone' as const,
              severity: 'info' as const,
              title: 'Courier Drone Dispatched',
              description: 'AeroRelay CR-1 launched on cross-partition transit corridor.'
            }
          ]
        }
      };
    });
  },

  pauseDrone: async () => {
    const { isPythonBackendConnected } = get();
    if (isPythonBackendConnected) {
      try {
        const nextState = await controlDroneApi('pause');
        set({ world: nextState });
        return;
      } catch (err) {
        console.warn('Python pause drone failed:', err);
      }
    }

    set(state => ({
      world: {
        ...state.world,
        drone: {
          ...state.world.drone,
          status: 'paused'
        }
      }
    }));
  },

  returnDrone: () => {
    set(state => {
      const tick = state.world.tick;
      const timestamp = formatSimTimestamp(tick);
      return {
        world: {
          ...state.world,
          drone: {
            ...state.world.drone,
            destinationNeighbourhood:
              state.world.drone.destinationNeighbourhood === 'neighbourhood_alpha'
                ? 'neighbourhood_bravo'
                : 'neighbourhood_alpha',
            status: 'returning'
          },
          events: [
            ...state.world.events,
            {
              id: `ev_drone_ret_${tick}`,
              tick,
              timestamp,
              category: 'drone' as const,
              severity: 'info' as const,
              title: 'Drone Return Commanded',
              description: 'CR-1 courier ordered to reverse trajectory towards base hub.'
            }
          ]
        }
      };
    });
  },

  selectEntity: entity => set({ selectedEntity: entity }),

  toggleOverlay: key =>
    set(state => ({
      overlays: {
        ...state.overlays,
        [key]: !state.overlays[key]
      }
    })),

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
