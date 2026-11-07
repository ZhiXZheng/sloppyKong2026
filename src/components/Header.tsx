import React from 'react';
import { useSimulationStore } from '../store/simulationStore';
import {
  Play,
  Pause,
  RotateCcw,
  StepForward,
  Radio,
  RadioTower,
  WifiOff,
  Zap,
  Activity,
  Send,
  CheckCircle2,
  AlertTriangle
} from 'lucide-react';

export const Header: React.FC = () => {
  const {
    world,
    isRunning,
    speed,
    togglePlayPause,
    stepTick,
    resetSimulation,
    setSpeed,
    toggleRadio,
    runPresetScenario,
    isPythonBackendConnected
  } = useSimulationStore();

  const isConnected = world.radioConnected;

  return (
    <header className="bg-[#0b1325] border-b border-[#1c2c4c] px-4 py-2.5 flex flex-wrap items-center justify-between gap-3 text-xs select-none">
      {/* Brand & Status */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          <div className="relative flex items-center justify-center w-8 h-8 rounded bg-gradient-to-br from-cyan-600 to-blue-800 text-white shadow-lg shadow-cyan-950/50 border border-cyan-400/40">
            <RadioTower className="w-5 h-5 text-cyan-200" />
            <div className="absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full bg-cyan-400 animate-ping" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-mono font-bold tracking-wider text-sm text-cyan-300">
                FLOODNET
              </span>
              <span className="text-[10px] tracking-widest px-1.5 py-0.5 rounded bg-cyan-950/80 text-cyan-400 border border-cyan-800/60 font-mono">
                AI-DISTRIBUTED RESCUE
              </span>
            </div>
            <p className="text-[10px] text-slate-400 font-mono">
              TACTICAL EMERGENCY DISPATCH // NEPTUNE NORTH SIM
            </p>
          </div>
        </div>

        <div className="h-6 w-[1px] bg-slate-800 mx-1 hidden sm:block" />

        {/* Live Simulation Indicator */}
        <div className="flex items-center gap-2 px-2.5 py-1 rounded bg-[#070b14] border border-slate-800">
          <span className="relative flex h-2 w-2">
            <span
              className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${
                isRunning ? 'bg-emerald-400' : 'bg-amber-400'
              }`}
            />
            <span
              className={`relative inline-flex rounded-full h-2 w-2 ${
                isRunning ? 'bg-emerald-500' : 'bg-amber-500'
              }`}
            />
          </span>
          <span className="font-mono text-[11px] font-semibold tracking-wide text-slate-200">
            {isRunning ? 'SIMULATION ACTIVE' : 'SIMULATION PAUSED'}
          </span>
          <span className="text-slate-600">|</span>
          <span className="font-mono text-cyan-400">
            TICK <span className="font-bold">{world.tick}</span>
          </span>
        </div>
      </div>

      {/* Primary Simulation Controls */}
      <div className="flex items-center gap-2">
        {/* Play / Pause */}
        <button
          onClick={togglePlayPause}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded font-mono font-medium text-xs transition-all shadow-sm ${
            isRunning
              ? 'bg-amber-600/90 hover:bg-amber-500 text-white shadow-amber-900/30'
              : 'bg-emerald-600 hover:bg-emerald-500 text-white shadow-emerald-900/30'
          }`}
          title={isRunning ? 'Pause simulation' : 'Start simulation'}
        >
          {isRunning ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
          <span>{isRunning ? 'PAUSE' : 'START'}</span>
        </button>

        {/* Step Forward 1 Tick */}
        <button
          onClick={stepTick}
          disabled={isRunning}
          className="flex items-center gap-1 px-2.5 py-1.5 rounded bg-slate-800/80 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed text-slate-200 border border-slate-700/80 font-mono"
          title="Advance 1 Tick"
        >
          <StepForward className="w-3.5 h-3.5 text-cyan-400" />
          <span>STEP</span>
        </button>

        {/* Reset */}
        <button
          onClick={() => resetSimulation()}
          className="flex items-center gap-1 px-2.5 py-1.5 rounded bg-slate-800/80 hover:bg-red-950/40 hover:text-red-300 text-slate-300 border border-slate-700/80 font-mono transition-colors"
          title="Reset to Initial Scenario"
        >
          <RotateCcw className="w-3.5 h-3.5" />
          <span>RESET</span>
        </button>

        {/* Speed Selector */}
        <div className="flex items-center bg-[#070b14] rounded border border-slate-800 p-0.5">
          {([1, 2, 4] as const).map(s => (
            <button
              key={s}
              onClick={() => setSpeed(s)}
              className={`px-2 py-1 rounded text-[11px] font-mono transition-colors ${
                speed === s
                  ? 'bg-cyan-900/80 text-cyan-300 font-bold border border-cyan-700/50'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {s}×
            </button>
          ))}
        </div>
      </div>

      {/* Prominent Radio Network Switch */}
      <div className="flex items-center gap-2">
        <button
          onClick={toggleRadio}
          className={`flex items-center gap-2 px-3 py-1.5 rounded font-mono font-bold text-xs transition-all border ${
            isConnected
              ? 'bg-cyan-950/60 border-cyan-500/80 text-cyan-300 hover:bg-cyan-900/50 shadow-sm shadow-cyan-900/30'
              : 'bg-red-950/80 border-red-500 text-red-300 hover:bg-red-900/70 shadow-md shadow-red-950/60 animate-pulse'
          }`}
          title="Toggle Radio Connectivity between Alpha and Bravo"
        >
          {isConnected ? (
            <>
              <Radio className="w-4 h-4 text-cyan-400 animate-pulse" />
              <span>RADIO: ONLINE</span>
            </>
          ) : (
            <>
              <WifiOff className="w-4 h-4 text-red-400" />
              <span>RADIO: OFFLINE (PARTITION)</span>
            </>
          )}
        </button>

        {/* Python Engine Indicator */}
        <div
          className={`flex items-center gap-1.5 px-2 py-1 rounded text-[10px] font-mono border ${
            isPythonBackendConnected
              ? 'bg-emerald-950/80 text-emerald-300 border-emerald-700/60'
              : 'bg-amber-950/80 text-amber-300 border-amber-700/60'
          }`}
          title="Python simulation engine status"
        >
          <span className={`w-1.5 h-1.5 rounded-full ${isPythonBackendConnected ? 'bg-emerald-400' : 'bg-amber-400'} animate-pulse`} />
          <span>{isPythonBackendConnected ? 'PYTHON ENGINE' : 'CLIENT ENGINE'}</span>
        </div>

        {/* Scenario Switcher */}
        <select
          onChange={e => resetSimulation(e.target.value)}
          defaultValue="small"
          className="bg-[#070b14] border border-slate-800 rounded px-2 py-1 text-[10px] font-mono text-cyan-300 focus:outline-none focus:border-cyan-500 cursor-pointer"
          title="Select scenario configuration"
        >
          <option value="small">Scenario: Small (2 Teams)</option>
          <option value="default">Scenario: Riverside (4 Teams)</option>
        </select>

        {/* Demo Scenario Preset Shortcuts */}
        <div className="hidden xl:flex items-center gap-1 bg-[#070b14] px-2 py-1 rounded border border-slate-800">
          <span className="text-[10px] text-slate-500 font-mono uppercase mr-1">Demo:</span>
          <button
            onClick={() => runPresetScenario('partition')}
            className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-slate-800/80 hover:bg-red-900/50 text-slate-300 hover:text-red-200 border border-slate-700/50"
            title="Step 2: Trigger Radio Failure"
          >
            Cut Radio
          </button>
          <button
            onClick={() => runPresetScenario('droneRelay')}
            className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-slate-800/80 hover:bg-purple-900/50 text-slate-300 hover:text-purple-200 border border-slate-700/50"
            title="Step 3: Launch Drone Relay"
          >
            Launch Drone
          </button>
          <button
            onClick={() => runPresetScenario('reconnect')}
            className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-slate-800/80 hover:bg-emerald-900/50 text-slate-300 hover:text-emerald-200 border border-slate-700/50"
            title="Step 4: Restore Radio & Reconcile"
          >
            Reconnect
          </button>
        </div>
      </div>
    </header>
  );
};
