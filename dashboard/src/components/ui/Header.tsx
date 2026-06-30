'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { LogOut } from 'lucide-react'
import { getSession, signOut, roleLabel, type Session } from '@/lib/auth'

type View = 'corridor' | 'kavach' | 'marl' | 'gate' | 'zone' | 'health'

function initials(name: string): string {
  const parts = name.split(/\s+/).map((p) => p.replace(/[^A-Za-z]/g, '')).filter(Boolean)
  if (parts.length === 0) return 'OC'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

const VIEW_TITLES: Record<View, { title: string; subtitle: string }> = {
  corridor: { title: 'Digital Twin — Corridor Map', subtitle: 'Real-time train positions & advisory overlays' },
  kavach: { title: 'Kavach++ Advisory Layer', subtitle: 'Physics-based braking curves — ADVISORY ONLY' },
  marl: { title: 'MARL Train Scheduler', subtitle: 'Multi-agent conflict-free rescheduling proposals' },
  gate: { title: 'Human Authorization Gate', subtitle: 'Risk-tiered advisory approval workflow' },
  zone: { title: 'Zone Compute', subtitle: 'Cross-station coordination — Federated Learning, HetGNN, GPU cluster' },
  health: { title: 'System Observability', subtitle: 'Infrastructure health & service status' },
}

export function Header({ activeView }: { activeView: View }) {
  const [time, setTime] = useState('')
  const [session, setSession] = useState<Session | null>(null)
  const router = useRouter()

  useEffect(() => {
    const tick = () => setTime(new Date().toLocaleTimeString('en-IN', { hour12: false }))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    setSession(getSession())
  }, [])

  function handleSignOut() {
    signOut()
    router.push('/')
  }

  const { title, subtitle } = VIEW_TITLES[activeView]
  const displayName = session?.name || 'Ctrl. Sharma'
  const displayRole = roleLabel(session?.role || 'Operations_Controller')

  return (
    <header className="h-16 bg-slate-950/80 backdrop-blur-sm border-b border-slate-800 flex items-center justify-between px-6">
      <div>
        <h2 className="text-base font-semibold text-white">{title}</h2>
        <p className="text-xs text-slate-500">{subtitle}</p>
      </div>
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-500">IST</span>
          <span className="font-mono text-white text-sm">{time}</span>
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/50 border border-slate-700">
          <div className="w-6 h-6 rounded-full bg-gradient-to-br from-orange-400 to-orange-600 flex items-center justify-center text-white text-[10px] font-bold">
            {initials(displayName)}
          </div>
          <div className="leading-tight">
            <div className="text-xs text-slate-200">{displayName}</div>
            <div className="text-[9px] text-slate-500">{displayRole}</div>
          </div>
        </div>
        <button
          onClick={handleSignOut}
          title="Sign out"
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-slate-400 hover:text-white hover:bg-slate-800/60 border border-slate-700 transition-colors"
        >
          <LogOut className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">Sign out</span>
        </button>
      </div>
    </header>
  )
}
