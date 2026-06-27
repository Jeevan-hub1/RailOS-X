'use client'

import { useEffect, useState } from 'react'

type View = 'corridor' | 'kavach' | 'marl' | 'gate' | 'health'

const VIEW_TITLES: Record<View, { title: string; subtitle: string }> = {
  corridor: { title: 'Digital Twin — Corridor Map', subtitle: 'Real-time train positions & advisory overlays' },
  kavach: { title: 'Kavach++ Advisory Layer', subtitle: 'Physics-based braking curves — ADVISORY ONLY' },
  marl: { title: 'MARL Train Scheduler', subtitle: 'Multi-agent conflict-free rescheduling proposals' },
  gate: { title: 'Human Authorization Gate', subtitle: 'Risk-tiered advisory approval workflow' },
  health: { title: 'System Observability', subtitle: 'Infrastructure health & service status' },
}

export function Header({ activeView }: { activeView: View }) {
  const [time, setTime] = useState('')

  useEffect(() => {
    const tick = () => setTime(new Date().toLocaleTimeString('en-IN', { hour12: false }))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [])

  const { title, subtitle } = VIEW_TITLES[activeView]

  return (
    <header className="h-16 bg-slate-950/80 backdrop-blur-sm border-b border-slate-800 flex items-center justify-between px-6">
      <div>
        <h2 className="text-base font-semibold text-white">{title}</h2>
        <p className="text-xs text-slate-500">{subtitle}</p>
      </div>
      <div className="flex items-center gap-6">
        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-500">IST</span>
          <span className="font-mono text-white text-sm">{time}</span>
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/50 border border-slate-700">
          <div className="w-6 h-6 rounded-full bg-gradient-to-br from-orange-400 to-orange-600 flex items-center justify-center text-white text-[10px] font-bold">
            OC
          </div>
          <span className="text-xs text-slate-300">Ctrl. Sharma</span>
        </div>
      </div>
    </header>
  )
}
