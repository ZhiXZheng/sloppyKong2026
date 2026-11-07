/**
 * Present one team's actual load, local knowledge, and delivered plan; distinguish AI advice
 * from standing-policy fallback.
 */
import React from 'react';
import { RescueTeam, TeamBeliefMap, AIRecommendation } from '../types/simulation';
import { BeliefMap } from './BeliefMap';
import {
  Users,
  Compass,
  Radio,
  Cpu,
  AlertCircle,
  CheckCircle,
  Truck,
  ShieldAlert,
  ArrowRight
} from 'lucide-react';

interface TeamPanelProps {
  team: RescueTeam;
  belief: TeamBeliefMap;
  recommendation: AIRecommendation;
  radioConnected: boolean;
  onSelectTeam?: () => void;
}

/** Show only the supplied team, its local belief map, and its current recommendation. */
export const TeamPanel: React.FC<TeamPanelProps> = ({
  team,
  belief,
  recommendation,
  radioConnected,
  onSelectTeam
}) => {
  const isAlpha = team.callsign === 'Alpha';
  const accentColor = isAlpha ? 'text-sky-400' : 'text-emerald-400';
  const borderColor = isAlpha ? 'border-sky-500/40' : 'border-emerald-500/40';
  const badgeBg = isAlpha ? 'bg-sky-950/70 border-sky-800' : 'bg-emerald-950/70 border-emerald-800';

  const knownCiviliansCount = Object.keys(belief.knownCivilians).length;

  return (
    <div
      onClick={onSelectTeam}
      className={`rounded-lg bg-[#0a1122] border ${borderColor} p-3.5 flex flex-col gap-3 shadow-lg transition-all hover:border-slate-500/60`}
    >
      {/* Header with Callsign & Status */}
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-2.5">
        <div className="flex items-center gap-2">
          <span
            className={`w-3 h-3 rounded-full ${
              isAlpha ? 'bg-sky-400 shadow-sky-500/50' : 'bg-emerald-400 shadow-emerald-500/50'
            } shadow-md`}
          />
          <div>
            <h3 className={`font-mono font-bold text-sm tracking-wide ${accentColor}`}>
              {team.name}
            </h3>
            <span className="text-[10px] font-mono text-slate-400">
              {team.neighbourhoodId === 'neighbourhood_alpha' ? 'West Sector Hub' : 'East Sector Hub'}
            </span>
          </div>
        </div>

        <div className="flex flex-col items-end">
          <span
            className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded border uppercase ${
              team.state === 'delivering'
                ? 'bg-amber-950/80 text-amber-300 border-amber-800 animate-pulse'
                : team.state === 'rescuing'
                ? 'bg-cyan-950/80 text-cyan-300 border-cyan-800'
                : team.state === 'moving'
                ? 'bg-blue-950/80 text-blue-300 border-blue-800'
                : 'bg-slate-800/80 text-slate-300 border-slate-700'
            }`}
          >
            {team.state}
          </span>
          <span className="text-[10px] font-mono text-slate-400 mt-0.5">
            GRID ({team.position.x}, {team.position.y})
          </span>
        </div>
      </div>

      {/* Operational Metrics Row */}
      <div className="grid grid-cols-3 gap-2 text-center text-xs font-mono">
        <div className="bg-[#070b14] border border-slate-800/80 rounded p-1.5">
          <div className="text-[10px] text-slate-500 uppercase">Load</div>
          <div className="font-bold text-slate-200 mt-0.5 flex items-center justify-center gap-1">
            <Users className="w-3 h-3 text-amber-400" />
            <span>{team.carriedCivilians}/{team.capacity}</span>
          </div>
        </div>

        <div className="bg-[#070b14] border border-slate-800/80 rounded p-1.5">
          <div className="text-[10px] text-slate-500 uppercase">Known Civs</div>
          <div className="font-bold text-cyan-400 mt-0.5">
            {knownCiviliansCount} groups
          </div>
        </div>

        <div className="bg-[#070b14] border border-slate-800/80 rounded p-1.5">
          <div className="text-[10px] text-slate-500 uppercase">Comms</div>
          <div className="font-bold mt-0.5 flex items-center justify-center gap-1">
            {radioConnected ? (
              <span className="text-emerald-400 flex items-center gap-0.5">
                <Radio className="w-2.5 h-2.5" /> LIVE
              </span>
            ) : (
              <span className="text-amber-400 flex items-center gap-0.5">
                <ShieldAlert className="w-2.5 h-2.5" /> DRONE
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Mock AI Intelligence Briefing Box */}
      <div className="bg-[#080d19] border border-slate-800 rounded-md p-2.5 flex flex-col gap-2">
        <div className="flex items-center justify-between text-xs font-mono">
          <div className="flex items-center gap-1.5 text-cyan-300">
            <Cpu className="w-3.5 h-3.5 text-cyan-400" />
            <span className="font-bold text-[11px] tracking-wide">AI RECOMMENDATION</span>
          </div>
          <span
            className={`text-[9px] px-1.5 py-0.5 rounded font-mono border ${
              recommendation.isAiFallback
                ? 'bg-amber-950/60 text-amber-400 border-amber-800/60'
                : 'bg-cyan-950/60 text-cyan-300 border-cyan-800/60'
            }`}
          >
            {recommendation.isAiFallback ? 'RULE FALLBACK' : 'CENTRAL AI'}
          </span>
        </div>

        <div>
          <div className="text-[11px] font-semibold text-slate-200 flex items-center gap-1 font-mono">
            <ArrowRight className="w-3 h-3 text-cyan-400 shrink-0" />
            <span>{recommendation.recommendedAction}</span>
          </div>
          <p className="text-[10px] text-slate-400 mt-1 leading-relaxed">
            "{recommendation.reasoning}"
          </p>
        </div>

        {/* Confidence & Missing Information */}
        <div className="space-y-1.5 pt-1.5 border-t border-slate-800/80 font-mono text-[10px]">
          <div className="flex items-center justify-between text-slate-400">
            <span>Confidence</span>
            <span className="text-cyan-400 font-bold">{recommendation.confidence}%</span>
          </div>
          <div className="w-full bg-slate-900 rounded-full h-1.5 overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ${
                recommendation.confidence > 80 ? 'bg-cyan-400' : 'bg-amber-400'
              }`}
              style={{ width: `${recommendation.confidence}%` }}
            />
          </div>

          <div className="text-[9px] text-amber-400/90 flex items-start gap-1 pt-1 leading-tight">
            <AlertCircle className="w-3 h-3 shrink-0 mt-0.5 text-amber-500" />
            <span>Missing: {recommendation.missingInformation}</span>
          </div>
        </div>
      </div>

      {/* Independent Miniature Belief Map */}
      <BeliefMap
        belief={belief}
        teamPosition={team.position}
        teamColor={team.color}
        teamCallsign={team.callsign}
      />
    </div>
  );
};
