/**
 * Dashboard composition and playback clock. Simulation state comes from the store; presentation
 * does not decide missions.
 */
import React, { useEffect } from 'react';
import { useSimulationStore } from './store/simulationStore';
import { Header } from './components/Header';
import { SimulationMap } from './components/SimulationMap';
import { TeamPanel } from './components/TeamPanel';
import { OperationalOverview } from './components/OperationalOverview';
import { EventFeed } from './components/EventFeed';
import { EntityDetailModal } from './components/EntityDetailModal';

/** Initialize the backend snapshot and schedule playback at 20 seconds divided by the selected speed. */
export const App: React.FC = () => {
  const { world, isRunning, speed, stepTick, selectEntity, init } = useSimulationStore();

  // Load state from Python backend on mount
  useEffect(() => {
    init();
  }, [init]);

  // Tick loop
  useEffect(() => {
    if (!isRunning) return;

    const intervalMs = 20_000 / speed; // 1x: 20s, 2x: 10s, 4x: 5s
    const interval = setInterval(() => {
      stepTick();
    }, intervalMs);

    return () => clearInterval(interval);
  }, [isRunning, speed, stepTick]);

  return (
    <div className="flex flex-col min-h-screen bg-[#070b14] text-slate-200 font-sans">
      {/* Top Bar */}
      <Header />

      {/* Main Dashboard Workspace */}
      <main className="flex-1 p-3 flex flex-col gap-3 max-w-[1920px] w-full mx-auto">
        {/* Core Layout: Left Overview, Center Map, Right Team Intelligence */}
        <div className="flex-1 flex flex-col xl:flex-row gap-3">
          {/* Left Sidebar: Operational Overview & Drone Dock */}
          <OperationalOverview />

          {/* Centerpiece: Simulation Map */}
          <div className="flex-1 flex flex-col min-w-0">
            <SimulationMap />
          </div>

          {/* Right Sidebar: Agent Intelligence & Independent Belief Maps */}
          <div className="w-full xl:w-80 flex flex-col gap-3 shrink-0">
            <div className="flex items-center justify-between text-xs font-mono font-bold text-slate-400 px-1 border-b border-slate-800 pb-1">
              <span>DISTRIBUTED AGENT INTELLIGENCE</span>
              <span className="text-[10px] text-cyan-400">INDEPENDENT BELIEFS</span>
            </div>

            {/* Team Alpha Panel */}
            <TeamPanel
              team={world.teams.alpha}
              belief={world.beliefs.alpha}
              recommendation={world.recommendations.alpha}
              radioConnected={world.radioConnected}
              onSelectTeam={() => selectEntity({ type: 'team', id: 'team_alpha' })}
            />

            {/* Team Bravo Panel */}
            <TeamPanel
              team={world.teams.bravo}
              belief={world.beliefs.bravo}
              recommendation={world.recommendations.bravo}
              radioConnected={world.radioConnected}
              onSelectTeam={() => selectEntity({ type: 'team', id: 'team_bravo' })}
            />
          </div>
        </div>

        {/* Bottom Section: Live Tactical Event Feed */}
        <EventFeed />
      </main>

      {/* Entity Inspector Detail Modal */}
      <EntityDetailModal />
    </div>
  );
};

export default App;
