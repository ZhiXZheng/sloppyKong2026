import React, { useEffect, useRef, useState } from 'react';
import { useSimulationStore } from '../store/simulationStore';
import {
  SimulationEvent,
  EventCategory,
  EventSeverity
} from '../types/simulation';
import {
  Radio,
  Plane,
  AlertTriangle,
  CheckCircle2,
  Cpu,
  Users,
  Compass,
  Filter,
  Terminal
} from 'lucide-react';

export const EventFeed: React.FC = () => {
  const { world } = useSimulationStore();
  const events = world.events;
  const feedEndRef = useRef<HTMLDivElement>(null);
  const [filterCategory, setFilterCategory] = useState<string>('all');

  // Auto-scroll to latest event
  useEffect(() => {
    feedEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events.length]);

  const filteredEvents = filterCategory === 'all'
    ? events
    : events.filter(e => e.category === filterCategory);

  const getCategoryIcon = (category: EventCategory) => {
    switch (category) {
      case 'network':
        return <Radio className="w-3.5 h-3.5 text-cyan-400" />;
      case 'drone':
        return <Plane className="w-3.5 h-3.5 text-purple-400" />;
      case 'rescue':
        return <Users className="w-3.5 h-3.5 text-emerald-400" />;
      case 'conflict':
        return <AlertTriangle className="w-3.5 h-3.5 text-red-400" />;
      case 'ai':
        return <Cpu className="w-3.5 h-3.5 text-blue-400" />;
      default:
        return <Compass className="w-3.5 h-3.5 text-slate-400" />;
    }
  };

  const getSeverityStyle = (severity: EventSeverity) => {
    switch (severity) {
      case 'danger':
        return 'border-l-2 border-red-500 bg-red-950/20 text-red-200';
      case 'warning':
        return 'border-l-2 border-amber-500 bg-amber-950/20 text-amber-200';
      case 'success':
        return 'border-l-2 border-emerald-500 bg-emerald-950/20 text-emerald-200';
      case 'info':
      default:
        return 'border-l-2 border-cyan-500/70 bg-cyan-950/15 text-slate-200';
    }
  };

  return (
    <div className="bg-[#0b1325] border border-[#1b2844] rounded-lg p-3 flex flex-col h-48 shadow-xl select-none">
      {/* Header & Category Filters */}
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-2 mb-2">
        <div className="flex items-center gap-2">
          <Terminal className="w-3.5 h-3.5 text-cyan-400" />
          <span className="text-xs font-mono font-bold text-cyan-300">
            TACTICAL EVENT STREAM
          </span>
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">
            {filteredEvents.length} EVENTS
          </span>
        </div>

        {/* Filter Badges */}
        <div className="flex items-center gap-1 text-[10px] font-mono">
          <Filter className="w-3 h-3 text-slate-500 mr-0.5" />
          {['all', 'network', 'drone', 'rescue', 'conflict'].map(cat => (
            <button
              key={cat}
              onClick={() => setFilterCategory(cat)}
              className={`px-1.5 py-0.5 rounded uppercase transition-colors ${
                filterCategory === cat
                  ? 'bg-cyan-900/80 text-cyan-300 font-bold border border-cyan-700/60'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>

      {/* Scrollable Event List */}
      <div className="flex-1 overflow-y-auto space-y-1.5 pr-1 font-mono text-xs">
        {filteredEvents.length === 0 ? (
          <div className="text-center text-slate-500 py-6 text-[11px]">
            No simulation events logged for selected filter.
          </div>
        ) : (
          filteredEvents.map(event => (
            <div
              key={event.id}
              className={`px-2.5 py-1.5 rounded-r transition-all flex items-start gap-2 ${getSeverityStyle(
                event.severity
              )}`}
            >
              <div className="shrink-0 mt-0.5">
                {getCategoryIcon(event.category)}
              </div>

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-slate-400 font-semibold">
                    [{event.timestamp}]
                  </span>
                  <span className="font-bold text-[11px] truncate">
                    {event.title}
                  </span>
                  <span className="text-[9px] px-1 py-0.2 rounded bg-slate-800 text-slate-400 uppercase ml-auto">
                    {event.category}
                  </span>
                </div>
                <p className="text-[10px] text-slate-300/90 leading-tight mt-0.5">
                  {event.description}
                </p>
              </div>
            </div>
          ))
        )}
        <div ref={feedEndRef} />
      </div>
    </div>
  );
};
