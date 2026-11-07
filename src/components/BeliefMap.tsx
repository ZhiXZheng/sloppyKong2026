/**
 * Render only a team's local observations so unknown cells remain visibly distinct from known
 * dry or flooded ground.
 */
import React, { useEffect, useState } from 'react';
import { TeamBeliefMap, GridPosition } from '../types/simulation';

interface BeliefMapProps {
  belief: TeamBeliefMap;
  teamPosition: GridPosition;
  teamColor: string;
  teamCallsign: string;
}

/** Convert received observations to a compact local-knowledge grid. */
export const BeliefMap: React.FC<BeliefMapProps> = ({
  belief,
  teamPosition,
  teamColor,
  teamCallsign
}) => {
  const [pulse, setPulse] = useState(false);

  // Trigger pulse effect when belief version updates
  useEffect(() => {
    if (belief.version > 1) {
      setPulse(true);
      const timer = setTimeout(() => setPulse(false), 800);
      return () => clearTimeout(timer);
    }
  }, [belief.version]);

  const totalCells = 400;
  const knownCellsCount = Object.keys(belief.grid).length;
  const unknownCellsCount = totalCells - knownCellsCount;
  const knownPercent = Math.round((knownCellsCount / totalCells) * 100);

  // 20x20 cell renderer
  const cells: React.ReactNode[] = [];
  for (let y = 0; y < 20; y++) {
    for (let x = 0; x < 20; x++) {
      const key = `${x},${y}`;
      const obs = belief.grid[key];
      const isTeamPos = teamPosition.x === x && teamPosition.y === y;

      let cellColor = '#131b2e'; // Unknown (slate dark grey)
      let title = `(${x},${y}): Unknown cell`;

      if (obs) {
        if (obs.state === 'flooded') {
          cellColor = '#1d4ed8'; // Known flooded (blue)
          title = `(${x},${y}): Flooded (Depth ${obs.waterDepth || 2})`;
        } else if (obs.state === 'safe') {
          cellColor = '#059669'; // Known safe (emerald green)
          title = `(${x},${y}): Safe/Dry ground`;
        } else if (obs.state === 'shelter') {
          cellColor = '#f59e0b'; // Shelter
          title = `(${x},${y}): Municipal Shelter`;
        } else if (obs.state === 'civilian') {
          cellColor = '#eab308'; // Civilian group
          title = `(${x},${y}): Civilian group detected!`;
        }
      }

      cells.push(
        <div
          key={key}
          title={title}
          className={`w-full h-full relative transition-colors duration-300 ${
            isTeamPos ? 'ring-1 ring-white z-10' : ''
          }`}
          style={{ backgroundColor: cellColor }}
        >
          {isTeamPos && (
            <div
              className="absolute inset-0 rounded-full animate-ping opacity-75"
              style={{ backgroundColor: teamColor }}
            />
          )}
        </div>
      );
    }
  }

  return (
    <div
      className={`rounded border bg-[#080d1a] p-2.5 transition-all duration-500 ${
        pulse
          ? 'border-cyan-400 shadow-md shadow-cyan-500/20'
          : 'border-slate-800/90'
      }`}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] font-mono tracking-wider text-slate-400 uppercase font-semibold">
            {teamCallsign} Local Belief Map
          </span>
          <span className="text-[9px] font-mono px-1 py-0.2 rounded bg-slate-800 text-slate-300">
            v{belief.version}
          </span>
        </div>
        <div className="text-[10px] font-mono text-cyan-400 font-bold">
          {knownPercent}% Known
        </div>
      </div>

      {/* 20x20 CSS Grid */}
      <div
        className="aspect-square w-full max-w-[210px] mx-auto bg-[#070b14] border border-slate-800 p-0.5 rounded shadow-inner gap-[1px]"
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(20, minmax(0, 1fr))',
          gridTemplateRows: 'repeat(20, minmax(0, 1fr))'
        }}
      >
        {cells}
      </div>

      {/* Belief map mini legend & telemetry */}
      <div className="mt-2 pt-2 border-t border-slate-800/80 flex items-center justify-between text-[9px] font-mono text-slate-400">
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-[1px] bg-[#131b2e] border border-slate-700" />
            <span>Unknown ({unknownCellsCount})</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-[1px] bg-[#059669]" />
            <span>Safe</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-[1px] bg-[#1d4ed8]" />
            <span>Flooded</span>
          </div>
        </div>
      </div>
    </div>
  );
};
