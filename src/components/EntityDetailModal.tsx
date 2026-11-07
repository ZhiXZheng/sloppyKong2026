import React from 'react';
import { useSimulationStore } from '../store/simulationStore';
import {
  X,
  Users,
  Compass,
  Plane,
  Shield,
  Layers,
  Radio,
  Clock,
  ArrowRight
} from 'lucide-react';

export const EntityDetailModal: React.FC = () => {
  const { world, selectedEntity, selectEntity } = useSimulationStore();

  if (!selectedEntity) return null;

  const { type, id, x, y } = selectedEntity;
  const { teams, civilians, shelter, drone, cells } = world;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs select-none">
      <div className="bg-[#0b1325] border border-[#1c2c4c] rounded-lg shadow-2xl w-full max-w-md overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="bg-[#070b14] border-b border-slate-800 px-4 py-2.5 flex items-center justify-between font-mono">
          <div className="flex items-center gap-2">
            <span className="text-cyan-400 font-bold text-xs uppercase tracking-wider">
              {type === 'team' && 'Tactical Team Telemetry'}
              {type === 'civilian' && 'Civilian Evacuee Status'}
              {type === 'drone' && 'AeroRelay Drone CR-1 Diagnostics'}
              {type === 'shelter' && 'Safe Zone Facility Status'}
              {type === 'cell' && `Grid Cell Diagnostics (${x}, ${y})`}
            </span>
          </div>
          <button
            onClick={() => selectEntity(null)}
            className="p-1 rounded text-slate-400 hover:text-slate-100 hover:bg-slate-800"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content Body */}
        <div className="p-4 font-mono text-xs space-y-3">
          {/* Team Detail */}
          {type === 'team' && (() => {
            const team = id === 'team_alpha' ? teams.alpha : teams.bravo;
            const belief = id === 'team_alpha' ? world.beliefs.alpha : world.beliefs.bravo;
            return (
              <div className="space-y-2">
                <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                  <span className="font-bold text-sm text-cyan-300">{team.name}</span>
                  <span className="px-2 py-0.5 rounded bg-cyan-950 text-cyan-400 border border-cyan-800 text-[10px]">
                    {team.state.toUpperCase()}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-2 text-slate-300">
                  <div>Position: <span className="font-bold text-white">({team.position.x}, {team.position.y})</span></div>
                  <div>Heading: <span className="font-bold text-white">{team.direction}</span></div>
                  <div>Carried: <span className="font-bold text-amber-300">{team.carriedCivilians} / {team.capacity}</span></div>
                  <div>Target ID: <span className="font-bold text-cyan-300">{team.currentTargetId || 'None'}</span></div>
                  <div>Known Cells: <span className="font-bold text-white">{Object.keys(belief.grid).length} / 400</span></div>
                  <div>Pending Msgs: <span className="font-bold text-white">{team.pendingOutgoingMessages.length}</span></div>
                </div>
              </div>
            );
          })()}

          {/* Civilian Detail */}
          {type === 'civilian' && (() => {
            const civ = civilians.find(c => c.groupId === id);
            if (!civ) return <div>Civilian group not found.</div>;
            return (
              <div className="space-y-2">
                <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                  <span className="font-bold text-sm text-amber-300">{civ.name}</span>
                  <span className={`px-2 py-0.5 rounded text-[10px] uppercase font-bold border ${
                    civ.status === 'delivered'
                      ? 'bg-emerald-950 text-emerald-300 border-emerald-800'
                      : civ.status === 'picked_up'
                      ? 'bg-cyan-950 text-cyan-300 border-cyan-800'
                      : 'bg-amber-950 text-amber-300 border-amber-800'
                  }`}>
                    {civ.status}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-2 text-slate-300">
                  <div>Location: <span className="font-bold text-white">({civ.position.x}, {civ.position.y})</span></div>
                  <div>Group Size: <span className="font-bold text-amber-300">👥 {civ.size} persons</span></div>
                  <div>Claimed By: <span className="font-bold text-cyan-300">{civ.claimedByTeamId || 'Unclaimed'}</span></div>
                  <div>Secured By: <span className="font-bold text-emerald-300">{civ.pickedUpByTeamId || 'None'}</span></div>
                </div>
                {civ.groupId === 'civ_2' && (
                  <div className="p-2 bg-red-950/40 border border-red-800/60 rounded text-[10px] text-red-300 leading-tight">
                    ★ Border Group: Located in contested central sector reachable by both teams during partition.
                  </div>
                )}
              </div>
            );
          })()}

          {/* Drone Detail */}
          {type === 'drone' && (
            <div className="space-y-2">
              <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                <span className="font-bold text-sm text-purple-300">{drone.name}</span>
                <span className="px-2 py-0.5 rounded bg-purple-950 text-purple-300 border border-purple-800 text-[10px] uppercase">
                  {drone.status}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-2 text-slate-300">
                <div>Current Pos: <span className="font-bold text-white">({drone.position.x}, {drone.position.y})</span></div>
                <div>Heading To: <span className="font-bold text-purple-300">{drone.destinationNeighbourhood}</span></div>
                <div>Queue Size: <span className="font-bold text-pink-400">✉ {drone.carriedMessages.length} packets</span></div>
                <div>Total Relayed: <span className="font-bold text-emerald-400">{drone.deliveryHistoryCount}</span></div>
              </div>
              {drone.carriedMessages.length > 0 && (
                <div className="mt-2 bg-[#070b14] border border-slate-800 rounded p-2 max-h-24 overflow-y-auto">
                  <div className="text-[10px] text-slate-400 font-bold mb-1">ONBOARD MESSAGE QUEUE:</div>
                  {drone.carriedMessages.map((m, i) => (
                    <div key={m.messageId} className="text-[10px] text-slate-300 py-0.5 border-b border-slate-900">
                      • [{m.type.toUpperCase()}] From {m.senderId} → {m.destinationNeighbourhood}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Shelter Detail */}
          {type === 'shelter' && (
            <div className="space-y-2">
              <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                <span className="font-bold text-sm text-amber-300">{shelter.name}</span>
                <span className="px-2 py-0.5 rounded bg-amber-950 text-amber-300 border border-amber-800 text-[10px]">
                  SECURE ZONE
                </span>
              </div>
              <div className="grid grid-cols-2 gap-2 text-slate-300">
                <div>Coordinates: <span className="font-bold text-white">({shelter.position.x}, {shelter.position.y})</span></div>
                <div>Capacity: <span className="font-bold text-white">{shelter.capacity} persons</span></div>
                <div>Current Occupants: <span className="font-bold text-emerald-400">{shelter.occupants} persons</span></div>
                <div>Remaining Spots: <span className="font-bold text-amber-400">{shelter.capacity - shelter.occupants}</span></div>
              </div>
            </div>
          )}

          {/* Cell Detail */}
          {type === 'cell' && x !== undefined && y !== undefined && (() => {
            const cell = cells[y][x];
            return (
              <div className="space-y-2">
                <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                  <span className="font-bold text-sm text-cyan-300">Cell ({x}, {y})</span>
                  <span className={`px-2 py-0.5 rounded text-[10px] ${
                    cell.isFlooded ? 'bg-blue-950 text-blue-300' : 'bg-emerald-950 text-emerald-300'
                  }`}>
                    {cell.isFlooded ? 'FLOODED' : 'DRY GROUND'}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-2 text-slate-300">
                  <div>Water Depth: <span className="font-bold text-blue-400">{cell.waterDepth} / 3</span></div>
                  <div>Submerged Road: <span className="font-bold text-white">{cell.isSubmergedRoad ? 'YES' : 'NO'}</span></div>
                  <div>Elevation: <span className="font-bold text-white">{cell.elevation} m</span></div>
                </div>
              </div>
            );
          })()}
        </div>

        {/* Footer */}
        <div className="bg-[#070b14] border-t border-slate-800 px-4 py-2 flex justify-end">
          <button
            onClick={() => selectEntity(null)}
            className="px-3 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-mono"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
