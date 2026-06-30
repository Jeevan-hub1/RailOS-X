'use client'

import { cn } from '@/lib/utils'

type View = 'corridor' | 'kavach' | 'marl' | 'gate' | 'zone' | 'health'

const NAV_ITEMS: { id: View; label: string; icon: string; badge?: string }[] = [
  { id: 'corridor', label: 'Corridor Map', icon: '🗺️' },
  { id: 'kavach', label: 'Kavach++', icon: '🛡️', badge: 'LIVE' },
  { id: 'marl', label: 'MARL Scheduler', icon: '🚂' },
  { id: 'gate', label: 'Auth Gate', icon: '🔐' },
  { id: 'zone', label: 'Zone Compute', icon: '🖥️' },
  { id: 'health', label: 'System Health', icon: '💚' },
]

export function Sidebar({ activeView, onNavigate }: { activeView: View; onNavigate: (v: View) => void }) {
  return (
    <aside className="w-64 bg-slate-950 border-r border-slate-800 flex flex-col">
      {/* Logo */}
      <div className="p-5 border-b border-slate-800">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-sky-500 to-blue-700 flex items-center justify-center text-white font-bold text-sm">
            RX
          </div>
          <div>
            <h1 className="text-base font-bold text-white">RailOS-X</h1>
            <p className="text-[10px] text-slate-500 uppercase tracking-wider">Operations Control</p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-3 space-y-1">
        <p className="text-[10px] uppercase tracking-wider text-slate-600 font-semibold px-3 mb-2">
          Subsystems
        </p>
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            onClick={() => onNavigate(item.id)}
            className={cn(
              'w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all',
              activeView === item.id
                ? 'bg-sky-600/20 text-sky-300 border border-sky-500/30'
                : 'text-slate-400 hover:text-white hover:bg-slate-800/50'
            )}
          >
            <span className="text-base">{item.icon}</span>
            <span className="flex-1 text-left">{item.label}</span>
            {item.badge && (
              <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                {item.badge}
              </span>
            )}
          </button>
        ))}
      </nav>

      {/* Footer */}
      <div className="p-4 border-t border-slate-800">
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <div className="status-indicator status-ok" />
          <span>Pilot Corridor Active</span>
        </div>
        <p className="text-[10px] text-slate-600 mt-1">NDLS — GZB — MERT</p>
      </div>
    </aside>
  )
}
