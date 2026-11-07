/**
 * SVG view of authoritative cells, entities, and actual planned routes. Network state remains in
 * the header/banner; decorative radio corridors are removed.
 */
import React, { useState } from 'react';
import { useSimulationStore } from '../store/simulationStore';
import {
  ZoomIn,
  ZoomOut,
  RotateCcw,
  Layers,
  Eye,
  WifiOff,
  Navigation,
  Shield,
  Users,
  Compass,
  Crosshair
} from 'lucide-react';
import { GridPosition } from '../types/simulation';

/** Render grid geometry and selectable entities while leaving all movement decisions to the simulation. */
export const SimulationMap: React.FC = () => {
  const { world, overlays, toggleOverlay, selectEntity, selectedEntity } =
    useSimulationStore();

  const [zoomLevel, setZoomLevel] = useState<number>(1);
  const [pan, setPan] = useState<{ x: number; y: number }>({ x: 0, y: 0 });

  const gridSize = 20;
  const cellSize = 36; // SVG viewBox coordinate units per cell
  const mapWidth = gridSize * cellSize; // 720
  const mapHeight = gridSize * cellSize; // 720

  /** Clamp visual magnification; this never changes grid coordinates or routes. */
  const handleZoom = (delta: number) => {
    setZoomLevel(prev => Math.min(Math.max(0.8, prev + delta), 2.2));
  };

  /** Restore map presentation without resetting simulation progress. */
  const handleResetView = () => {
    setZoomLevel(1);
    setPan({ x: 0, y: 0 });
  };

  const { cells, teams, civilians, shelter, drone, radioConnected } = world;

  // Drone route SVG path string
  const droneRoutePath = drone.routeWaypoints
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x * cellSize + cellSize / 2} ${p.y * cellSize + cellSize / 2}`)
    .join(' ') + ' Z';

  // Planned route paths for teams
  const alphaRoutePath = teams.alpha.plannedRoute.length > 0
    ? `M ${teams.alpha.position.x * cellSize + cellSize / 2} ${teams.alpha.position.y * cellSize + cellSize / 2} ` +
      teams.alpha.plannedRoute
        .map(p => `L ${p.x * cellSize + cellSize / 2} ${p.y * cellSize + cellSize / 2}`)
        .join(' ')
    : '';

  const bravoRoutePath = teams.bravo.plannedRoute.length > 0
    ? `M ${teams.bravo.position.x * cellSize + cellSize / 2} ${teams.bravo.position.y * cellSize + cellSize / 2} ` +
      teams.bravo.plannedRoute
        .map(p => `L ${p.x * cellSize + cellSize / 2} ${p.y * cellSize + cellSize / 2}`)
        .join(' ')
    : '';

  return (
    <div className="relative flex-1 flex flex-col bg-[#070b14] border border-[#1b2844] rounded-lg overflow-hidden shadow-2xl">
      {/* Map Header / Control Bar */}
      <div className="bg-[#0b1325] border-b border-[#1c2c4c] px-3.5 py-2 flex items-center justify-between z-10 select-none">
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 text-xs font-mono font-bold text-cyan-300">
            <Crosshair className="w-3.5 h-3.5 text-cyan-400" />
            <span>GEO-TACTICAL DISPATCH GRID [20×20]</span>
          </div>
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 hidden sm:inline">
            COORDINATES 0,0 → 19,19
          </span>
        </div>

        {/* Overlay toggles & Zoom Controls */}
        <div className="flex items-center gap-2">
          {/* Overlay Toggles */}
          <div className="flex items-center bg-[#070b14] border border-slate-800 rounded px-1 py-0.5 gap-1 text-[11px] font-mono">
            <button
              onClick={() => toggleOverlay('flood')}
              className={`px-1.5 py-0.5 rounded transition-colors ${
                overlays.flood ? 'bg-blue-900/70 text-blue-300 font-bold' : 'text-slate-500'
              }`}
              title="Toggle Flood Overlay"
            >
              Water
            </button>
            <button
              onClick={() => toggleOverlay('routes')}
              className={`px-1.5 py-0.5 rounded transition-colors ${
                overlays.routes ? 'bg-amber-900/70 text-amber-300 font-bold' : 'text-slate-500'
              }`}
              title="Toggle Team & Drone Routes"
            >
              Routes
            </button>
            <button
              onClick={() => toggleOverlay('civilians')}
              className={`px-1.5 py-0.5 rounded transition-colors ${
                overlays.civilians ? 'bg-yellow-900/70 text-yellow-300 font-bold' : 'text-slate-500'
              }`}
              title="Toggle Civilian Markers"
            >
              Civilians
            </button>
          </div>

          {/* Zoom In / Out */}
          <div className="flex items-center bg-[#070b14] border border-slate-800 rounded p-0.5">
            <button
              onClick={() => handleZoom(0.15)}
              className="p-1 text-slate-400 hover:text-cyan-300"
              title="Zoom In"
            >
              <ZoomIn className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={() => handleZoom(-0.15)}
              className="p-1 text-slate-400 hover:text-cyan-300"
              title="Zoom Out"
            >
              <ZoomOut className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={handleResetView}
              className="p-1 text-slate-400 hover:text-slate-200"
              title="Reset View"
            >
              <RotateCcw className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* Network Partition Banner Overlay if disconnected */}
      {!radioConnected && (
        <div className="absolute top-11 inset-x-0 z-20 bg-red-950/90 border-y border-red-500/70 py-1 px-4 flex items-center justify-between text-xs font-mono text-red-200 shadow-lg backdrop-blur-sm animate-pulse">
          <div className="flex items-center gap-2">
            <WifiOff className="w-4 h-4 text-red-400" />
            <span className="font-bold tracking-wider">
              NETWORK PARTITION ACTIVE: RADIO CONNECTION INTERRUPTED
            </span>
          </div>
          <span className="text-[11px] text-red-300">
            TEAMS OPERATING ON LOCAL BELIEFS // RELYING ON COURIER DRONE
          </span>
        </div>
      )}

      {/* SVG Canvas Area */}
      <div className="relative flex-1 flex items-center justify-center p-2 bg-[#050811] overflow-hidden">
        <svg
          viewBox={`0 0 ${mapWidth} ${mapHeight}`}
          className="w-full h-full max-h-[calc(100vh-220px)] object-contain transition-transform duration-200"
          style={{ transform: `scale(${zoomLevel})` }}
        >
          <defs>
            {/* Glow filters */}
            <filter id="glow-cyan" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="3" result="blur" />
              <feComposite in="SourceGraphic" in2="blur" operator="over" />
            </filter>
            <filter id="glow-green" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="3" result="blur" />
              <feComposite in="SourceGraphic" in2="blur" operator="over" />
            </filter>
            <filter id="glow-red" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="4" result="blur" />
              <feComposite in="SourceGraphic" in2="blur" operator="over" />
            </filter>

            {/* Pattern for roads */}
            <pattern id="road-hatch" width="4" height="4" patternTransform="rotate(45 0 0)" patternUnits="userSpaceOnUse">
              <line x1="0" y1="0" x2="0" y2="4" stroke="#f59e0b" strokeWidth="1" opacity="0.3" />
            </pattern>
          </defs>

          {/* 1. Base Grid Cells & Flood Depths */}
          {cells.map((row, y) =>
            row.map((cell, x) => {
              const cx = x * cellSize;
              const cy = y * cellSize;

              let fillColor = '#0b1325'; // Dry urban ground
              let strokeColor = '#15213b';

              if (overlays.flood && cell.isFlooded) {
                if (cell.waterDepth === 1) {
                  fillColor = '#1e3a8a'; // Shallow flood
                } else if (cell.waterDepth === 2) {
                  fillColor = '#1d4ed8'; // Medium flood
                } else {
                  fillColor = '#1d4ed8'; // Initial channel matches spreading floodwater
                }
              }

              return (
                <g key={`cell_${x}_${y}`}>
                  <rect
                    x={cx}
                    y={cy}
                    width={cellSize}
                    height={cellSize}
                    fill={fillColor}
                    stroke={strokeColor}
                    strokeWidth={0.8}
                    onClick={() => selectEntity({ type: 'cell', x, y })}
                    className="cursor-pointer hover:stroke-cyan-400 hover:stroke-[1.5] transition-colors"
                  />
                  {/* Road marking indicator if submerged road */}
                  {cell.isSubmergedRoad && (
                    <rect
                      x={cx + 1}
                      y={cy + 1}
                      width={cellSize - 2}
                      height={cellSize - 2}
                      fill="url(#road-hatch)"
                      opacity={0.4}
                    />
                  )}
                </g>
              );
            })
          )}

          {/* Radio connectivity is shown in the header/banner; decorative
              corridor circles and the fixed inter-sector beam are intentionally absent. */}
          {/* 4. Routes (Team & Drone) */}
          {overlays.routes && (
            <>
              {/* Courier Drone Fixed Route */}
              <path
                d={droneRoutePath}
                fill="none"
                stroke="#a855f7"
                strokeWidth={1.5}
                strokeDasharray="4 4"
                opacity={0.6}
              />

              {/* Team Alpha Planned Route */}
              {alphaRoutePath && (
                <path
                  d={alphaRoutePath}
                  fill="none"
                  stroke="#38bdf8"
                  strokeWidth={2}
                  strokeDasharray="3 3"
                  opacity={0.8}
                />
              )}

              {/* Team Bravo Planned Route */}
              {bravoRoutePath && (
                <path
                  d={bravoRoutePath}
                  fill="none"
                  stroke="#22c55e"
                  strokeWidth={2}
                  strokeDasharray="3 3"
                  opacity={0.8}
                />
              )}
            </>
          )}

          {/* 5. Municipal Shelter Facility */}
          <g
            transform={`translate(${shelter.position.x * cellSize + 2}, ${shelter.position.y * cellSize + 2})`}
            onClick={() => selectEntity({ type: 'shelter', id: shelter.shelterId })}
            className="cursor-pointer"
          >
            <rect
              width={cellSize - 4}
              height={cellSize - 4}
              rx={4}
              fill="#d97706"
              stroke="#fbbf24"
              strokeWidth={1.5}
            />
            <text
              x={(cellSize - 4) / 2}
              y={(cellSize - 4) / 2 + 4}
              fill="#ffffff"
              fontSize="14"
              fontWeight="bold"
              textAnchor="middle"
            >
              🏥
            </text>
            <text
              x={(cellSize - 4) / 2}
              y={cellSize + 6}
              fill="#fbbf24"
              fontSize="9"
              fontFamily="monospace"
              fontWeight="bold"
              textAnchor="middle"
            >
              SHELTER ({shelter.occupants})
            </text>
          </g>

          {/* 6. Civilian Groups */}
          {overlays.civilians &&
            civilians.map(c => {
              const isDelivered = c.status === 'delivered';
              const isPickedUp = c.status === 'picked_up';
              const isClaimed = c.status === 'claimed';
              const isBorderContested = c.groupId === 'civ_2';

              const cx = c.position.x * cellSize + cellSize / 2;
              const cy = c.position.y * cellSize + cellSize / 2;

              if (isDelivered) return null; // Rescued and now in shelter

              return (
                <g
                  key={c.groupId}
                  transform={`translate(${cx}, ${cy})`}
                  onClick={() => selectEntity({ type: 'civilian', id: c.groupId })}
                  className="cursor-pointer"
                >
                  {/* Pulsing ring if awaiting rescue or contested */}
                  {!isPickedUp && (
                    <circle
                      r={14}
                      fill={isBorderContested && !radioConnected ? '#ef4444' : '#eab308'}
                      fillOpacity={0.2}
                      className="animate-ping"
                    />
                  )}

                  <circle
                    r={11}
                    fill={isPickedUp ? '#06b6d4' : isBorderContested && !radioConnected ? '#f97316' : '#eab308'}
                    stroke="#ffffff"
                    strokeWidth={1.5}
                  />

                  <text
                    y={3.5}
                    fill="#000000"
                    fontSize="9"
                    fontWeight="bold"
                    fontFamily="monospace"
                    textAnchor="middle"
                  >
                    👥{c.size}
                  </text>

                  {/* Group name label */}
                  <text
                    y={-14}
                    fill={isBorderContested && !radioConnected ? '#f87171' : '#fef08a'}
                    fontSize="8.5"
                    fontFamily="monospace"
                    fontWeight="bold"
                    textAnchor="middle"
                  >
                    {c.groupId === 'civ_2' ? '★ BORDER CIV' : c.groupId.toUpperCase()}
                  </text>
                </g>
              );
            })}

          {/* 7. Courier Drone Marker */}
          <g
            transform={`translate(${drone.position.x * cellSize + cellSize / 2}, ${
              drone.position.y * cellSize + cellSize / 2
            })`}
            onClick={() => selectEntity({ type: 'drone', id: drone.droneId })}
            className="cursor-pointer"
          >
            {/* Drone pulse */}
            <circle r={14} fill="#a855f7" fillOpacity={0.25} className="animate-pulse" />
            <circle r={9} fill="#9333ea" stroke="#d8b4fe" strokeWidth={1.8} />

            {/* Drone Icon / Rotor */}
            <text y={3} fill="#ffffff" fontSize="9" textAnchor="middle">
              ✈
            </text>

            {/* Carried Messages Count Badge */}
            <g transform="translate(8, -10)">
              <rect
                width={16}
                height={12}
                rx={2}
                fill={drone.carriedMessages.length > 0 ? '#ec4899' : '#475569'}
                stroke="#ffffff"
                strokeWidth={0.8}
              />
              <text
                x={8}
                y={9}
                fill="#ffffff"
                fontSize="8"
                fontFamily="monospace"
                fontWeight="bold"
                textAnchor="middle"
              >
                ✉{drone.carriedMessages.length}
              </text>
            </g>

            <text
              y={21}
              fill="#d8b4fe"
              fontSize="8.5"
              fontFamily="monospace"
              fontWeight="bold"
              textAnchor="middle"
            >
              CR-1 RELAY
            </text>
          </g>

          {/* 8. Rescue Team Alpha (Blue) */}
          <g
            transform={`translate(${teams.alpha.position.x * cellSize + cellSize / 2}, ${
              teams.alpha.position.y * cellSize + cellSize / 2
            })`}
            onClick={() => selectEntity({ type: 'team', id: teams.alpha.teamId })}
            className="cursor-pointer"
          >
            <circle r={15} fill="#0284c7" fillOpacity={0.2} className="animate-ping" />
            <polygon
              points="0,-12 10,8 -10,8"
              fill="#38bdf8"
              stroke="#ffffff"
              strokeWidth={1.5}
              transform={
                teams.alpha.direction === 'N'
                  ? 'rotate(0)'
                  : teams.alpha.direction === 'E'
                  ? 'rotate(90)'
                  : teams.alpha.direction === 'S'
                  ? 'rotate(180)'
                  : teams.alpha.direction === 'W'
                  ? 'rotate(270)'
                  : 'rotate(0)'
              }
            />
            {/* Team Alpha Label */}
            <text
              y={22}
              fill="#38bdf8"
              fontSize="9"
              fontFamily="monospace"
              fontWeight="bold"
              textAnchor="middle"
            >
              ALPHA [{teams.alpha.carriedCivilians > 0 ? `+${teams.alpha.carriedCivilians}` : '0'}]
            </text>
          </g>

          {/* 9. Rescue Team Bravo (Green) */}
          <g
            transform={`translate(${teams.bravo.position.x * cellSize + cellSize / 2}, ${
              teams.bravo.position.y * cellSize + cellSize / 2
            })`}
            onClick={() => selectEntity({ type: 'team', id: teams.bravo.teamId })}
            className="cursor-pointer"
          >
            <circle r={15} fill="#16a34a" fillOpacity={0.2} className="animate-ping" />
            <polygon
              points="0,-12 10,8 -10,8"
              fill="#22c55e"
              stroke="#ffffff"
              strokeWidth={1.5}
              transform={
                teams.bravo.direction === 'N'
                  ? 'rotate(0)'
                  : teams.bravo.direction === 'E'
                  ? 'rotate(90)'
                  : teams.bravo.direction === 'S'
                  ? 'rotate(180)'
                  : teams.bravo.direction === 'W'
                  ? 'rotate(270)'
                  : 'rotate(0)'
              }
            />
            {/* Team Bravo Label */}
            <text
              y={22}
              fill="#22c55e"
              fontSize="9"
              fontFamily="monospace"
              fontWeight="bold"
              textAnchor="middle"
            >
              BRAVO [{teams.bravo.carriedCivilians > 0 ? `+${teams.bravo.carriedCivilians}` : '0'}]
            </text>
          </g>
        </svg>
      </div>

      {/* Map Legend Footer */}
      <div className="bg-[#0b1325] border-t border-[#1c2c4c] px-3 py-1.5 flex flex-wrap items-center justify-between text-[10px] font-mono text-slate-400 gap-2 select-none z-10">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded-full bg-[#38bdf8]" />
            <span>Alpha Team</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded-full bg-[#22c55e]" />
            <span>Bravo Team</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded-full bg-[#a855f7]" />
            <span>Courier Drone (CR-1)</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded-full bg-[#eab308]" />
            <span>Civilian Group</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded bg-[#d97706]" />
            <span>Safe Shelter</span>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1">
            <span className="w-2.5 h-2 bg-[#1e3a8a] border border-slate-700" />
            <span>Shallow</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="w-2.5 h-2 bg-[#1d4ed8]" />
            <span>Moderate</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="w-2.5 h-2 bg-[#1d4ed8]" />
            <span>Deep Flood</span>
          </div>
        </div>
      </div>
    </div>
  );
};
