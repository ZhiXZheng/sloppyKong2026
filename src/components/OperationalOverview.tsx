import React from 'react';
import { useSimulationStore } from '../store/simulationStore';
import {
  Users,
  ShieldCheck,
  Radio,
  Send,
  Plane,
  AlertTriangle,
  Play,
  Pause,
  RotateCcw,
  CheckCircle2,
  Activity,
  Layers
} from 'lucide-react';

export const OperationalOverview: React.FC = () => {
  const { world, launchDrone, pauseDrone, returnDrone } = useSimulationStore();
  const { stats, radioConnected, drone, teams, shelter } = world;

  const rescuePercent = Math.round((stats.rescuedCivilians / stats.totalCivilians) * 100);

  return (
    <div className="w-full lg:w-72 bg-[#0b1325] border border-[#1b2844] rounded-lg p-3.5 flex flex-col gap-3.5 shadow-xl select-none">
      {/* Title */}
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-2">
        <div className="flex items-center gap-1.5 text-xs font-mono font-bold text-cyan-300">
          <Activity className="w-3.5 h-3.5 text-cyan-400" />
          <span>MISSION OVERVIEW</span>
        </div>
        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-300">
          STAGE 1
        </span>
      </div>

      {/* Progress Bar */}
      <div className="bg-[#070b14] border border-slate-800 rounded p-2.5 space-y-1.5">
        <div className="flex items-center justify-between text-xs font-mono">
          <span className="text-slate-400">Mission Progress</span>
          <span className="font-bold text-emerald-400">{rescuePercent}% Complete</span>
        </div>
        <div className="w-full bg-slate-900 rounded-full h-2 overflow-hidden border border-slate-800">
          <div
            className="h-full bg-gradient-to-r from-cyan-500 to-emerald-400 transition-all duration-500"
            style={{ width: `${rescuePercent}%` }}
          />
        </div>
        <div className="flex justify-between text-[10px] font-mono text-slate-500 pt-0.5">
          <span>0 evacuees</span>
          <span>Target: {stats.totalCivilians} evacuees</span>
        </div>
      </div>

      {/* Primary Key Stats Grid */}
      <div className="grid grid-cols-2 gap-2 text-xs font-mono">
        {/* Civilians Rescued */}
        <div className="bg-[#070b14] border border-slate-800 rounded p-2 flex flex-col justify-between">
          <span className="text-[10px] text-slate-400 flex items-center gap-1">
            <ShieldCheck className="w-3 h-3 text-emerald-400" /> Rescued
          </span>
          <div className="text-lg font-bold text-emerald-400 mt-1">
            {stats.rescuedCivilians} <span className="text-xs text-slate-500">/ {stats.totalCivilians}</span>
          </div>
        </div>

        {/* Civilians Awaiting Rescue */}
        <div className="bg-[#070b14] border border-slate-800 rounded p-2 flex flex-col justify-between">
          <span className="text-[10px] text-slate-400 flex items-center gap-1">
            <Users className="w-3 h-3 text-amber-400" /> At Risk
          </span>
          <div className="text-lg font-bold text-amber-400 mt-1">
            {stats.awaitingRescue}
          </div>
        </div>

        {/* Radio Link Status */}
        <div className="bg-[#070b14] border border-slate-800 rounded p-2 flex flex-col justify-between">
          <span className="text-[10px] text-slate-400 flex items-center gap-1">
            <Radio className="w-3 h-3 text-cyan-400" /> Radio Link
          </span>
          <div className={`text-xs font-bold mt-1 ${radioConnected ? 'text-cyan-300' : 'text-red-400 animate-pulse'}`}>
            {radioConnected ? 'ONLINE' : 'PARTITION'}
          </div>
        </div>

        {/* Contested Conflicts */}
        <div className="bg-[#070b14] border border-slate-800 rounded p-2 flex flex-col justify-between">
          <span className="text-[10px] text-slate-400 flex items-center gap-1">
            <AlertTriangle className="w-3 h-3 text-red-400" /> Task Conflicts
          </span>
          <div className={`text-xs font-bold mt-1 ${stats.activeConflicts > 0 ? 'text-red-400 animate-pulse' : 'text-slate-300'}`}>
            {stats.activeConflicts > 0 ? `${stats.activeConflicts} ACTIVE` : `${stats.resolvedConflicts} Resolved`}
          </div>
        </div>
      </div>

      {/* Courier Drone Operations Module */}
      <div className="bg-[#080d1a] border border-purple-900/50 rounded-lg p-2.5 flex flex-col gap-2 shadow-inner">
        <div className="flex items-center justify-between border-b border-purple-950 pb-1.5">
          <div className="flex items-center gap-1.5 text-xs font-mono font-bold text-purple-300">
            <Plane className="w-3.5 h-3.5 text-purple-400" />
            <span>COURIER DRONE CR-1</span>
          </div>
          <span
            className={`text-[9px] font-mono px-1.5 py-0.5 rounded uppercase font-bold border ${
              drone.status === 'flying' || drone.status === 'returning'
                ? 'bg-purple-950/80 text-purple-300 border-purple-700 animate-pulse'
                : 'bg-slate-800 text-slate-400 border-slate-700'
            }`}
          >
            {drone.status}
          </span>
        </div>

        {/* Drone Telemetry */}
        <div className="grid grid-cols-2 gap-1.5 text-[11px] font-mono text-slate-300">
          <div>
            <span className="text-slate-500 text-[10px] block">PAYLOAD</span>
            <span className="font-bold text-pink-400">✉ {drone.carriedMessages.length} packets</span>
          </div>
          <div>
            <span className="text-slate-500 text-[10px] block">DELIVERED</span>
            <span className="font-bold text-emerald-400">{drone.deliveryHistoryCount} pkts</span>
          </div>
          <div>
            <span className="text-slate-500 text-[10px] block">COORDINATES</span>
            <span>({drone.position.x}, {drone.position.y})</span>
          </div>
          <div>
            <span className="text-slate-500 text-[10px] block">HEADING</span>
            <span className="text-purple-300">{drone.destinationNeighbourhood === 'neighbourhood_bravo' ? 'Bravo (East)' : 'Alpha (West)'}</span>
          </div>
        </div>

        {/* Drone Action Controls */}
        <div className="flex items-center gap-1.5 pt-1">
          <button
            onClick={launchDrone}
            className="flex-1 py-1 rounded bg-purple-900/60 hover:bg-purple-800 text-purple-200 text-[11px] font-mono font-bold border border-purple-700/60 transition-colors flex items-center justify-center gap-1"
          >
            <Play className="w-3 h-3" />
            <span>Launch</span>
          </button>
          <button
            onClick={pauseDrone}
            className="flex-1 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] font-mono font-medium border border-slate-700 transition-colors flex items-center justify-center gap-1"
          >
            <Pause className="w-3 h-3" />
            <span>Pause</span>
          </button>
          <button
            onClick={returnDrone}
            className="px-2 py-1 rounded bg-slate-800 hover:bg-purple-950 text-slate-300 hover:text-purple-300 text-[11px] font-mono border border-slate-700 transition-colors"
            title="Reverse Route"
          >
            <RotateCcw className="w-3 h-3" />
          </button>
        </div>
      </div>

      {/* Shelter Facility Status */}
      <div className="bg-[#070b14] border border-amber-900/40 rounded p-2 flex items-center justify-between font-mono text-xs">
        <div className="flex items-center gap-2">
          <span className="text-base">🏥</span>
          <div>
            <div className="font-bold text-amber-300 text-[11px]">{shelter.name}</div>
            <div className="text-[10px] text-slate-400">Position ({shelter.position.x}, {shelter.position.y})</div>
          </div>
        </div>
        <div className="text-right">
          <div className="font-bold text-amber-400">{shelter.occupants} / {shelter.capacity}</div>
          <div className="text-[9px] text-slate-500 uppercase">Occupants</div>
        </div>
      </div>
    </div>
  );
};
