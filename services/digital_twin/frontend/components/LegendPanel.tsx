/**
 * Persistent Legend Panel (Req 45 C4, Req 34 C1)
 * Always visible — defines all visual encoding conventions.
 */
import React from 'react';

const LEGEND_ITEMS = [
  { icon: '●', color: 'text-green-400',  label: 'Confirmed (live sensor data)',  style: 'solid' },
  { icon: '◌', color: 'text-blue-300',   label: 'Predicted (ML forecast)',        style: 'dashed' },
  { icon: '▨', color: 'text-gray-400',   label: 'Simulated (MARL/OpenTrack)',     style: 'hatched' },
  { icon: '○', color: 'text-amber-300',  label: 'Stale (>10s no update)',         style: 'faded' },
  { icon: '▲', color: 'text-yellow-300', label: 'Advisory (Kavach++) — NOT CERTIFIED', style: 'advisory' },
];

const SEVERITY_ITEMS = [
  { color: 'bg-red-600',    label: 'CRITICAL' },
  { color: 'bg-amber-500',  label: 'HIGH' },
  { color: 'bg-yellow-400', label: 'MEDIUM' },
  { color: 'bg-blue-500',   label: 'LOW' },
];

export default function LegendPanel() {
  return (
    <div className="border-t border-gray-700 p-3 bg-gray-850 text-xs">
      <div className="font-semibold text-gray-300 mb-2 uppercase tracking-wide">Map Legend</div>
      <div className="space-y-1 mb-3">
        {LEGEND_ITEMS.map(item => (
          <div key={item.label} className="flex items-center gap-2">
            <span className={`${item.color} w-4 text-center`}>{item.icon}</span>
            <span className="text-gray-300">{item.label}</span>
          </div>
        ))}
      </div>
      <div className="font-semibold text-gray-300 mb-2 uppercase tracking-wide">Severity</div>
      <div className="flex flex-wrap gap-1">
        {SEVERITY_ITEMS.map(s => (
          <span key={s.label} className={`${s.color} px-2 py-0.5 rounded text-white font-bold`}>
            {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}
