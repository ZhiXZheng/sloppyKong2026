import { SimulationWorld } from '../types/simulation';

const API_BASE = '/api';

export async function fetchState(): Promise<SimulationWorld> {
  const res = await fetch(`${API_BASE}/state`);
  if (!res.ok) {
    throw new Error(`Failed to fetch state: ${res.statusText}`);
  }
  return res.json();
}

export async function stepSimulationApi(): Promise<SimulationWorld> {
  const res = await fetch(`${API_BASE}/step`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  });
  if (!res.ok) {
    throw new Error(`Failed to step simulation: ${res.statusText}`);
  }
  return res.json();
}

export async function resetSimulationApi(scenario: string = 'small'): Promise<SimulationWorld> {
  const res = await fetch(`${API_BASE}/reset`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scenario })
  });
  if (!res.ok) {
    throw new Error(`Failed to reset simulation: ${res.statusText}`);
  }
  return res.json();
}

export async function toggleRadioApi(connected: boolean): Promise<SimulationWorld> {
  const res = await fetch(`${API_BASE}/radio`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ connected })
  });
  if (!res.ok) {
    throw new Error(`Failed to toggle radio: ${res.statusText}`);
  }
  return res.json();
}

export async function controlDroneApi(action: 'launch' | 'pause' | 'return'): Promise<SimulationWorld> {
  const res = await fetch(`${API_BASE}/drone`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action })
  });
  if (!res.ok) {
    throw new Error(`Failed to control drone: ${res.statusText}`);
  }
  return res.json();
}
