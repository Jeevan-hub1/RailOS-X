'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Sidebar } from '@/components/ui/Sidebar'
import { Header } from '@/components/ui/Header'
import { CorridorMap } from '@/components/corridor/CorridorMap'
import { KavachPanel } from '@/components/kavach/KavachPanel'
import { MARLPanel } from '@/components/marl/MARLPanel'
import { GatePanel } from '@/components/gate/GatePanel'
import { HealthPanel } from '@/components/health/HealthPanel'
import { ZonePanel } from '@/components/zone/ZonePanel'
import { isAuthenticated } from '@/lib/auth'

type View = 'corridor' | 'kavach' | 'marl' | 'gate' | 'zone' | 'health'

export default function Dashboard() {
  const [activeView, setActiveView] = useState<View>('corridor')
  const router = useRouter()
  const [ready, setReady] = useState(false)

  // Client-side auth guard (demo). Redirects to /login when not signed in.
  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace('/login')
    } else {
      setReady(true)
    }
  }, [router])

  if (!ready) {
    return (
      <div className="flex h-screen items-center justify-center text-slate-500">
        <div className="flex items-center gap-3">
          <div className="w-4 h-4 rounded-full border-2 border-sky-500 border-t-transparent animate-spin" />
          <span className="text-sm">Authenticating…</span>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar activeView={activeView} onNavigate={setActiveView} />
      <div className="flex-1 flex flex-col overflow-hidden">
        <Header activeView={activeView} />
        <main className="flex-1 overflow-auto p-4 lg:p-6">
          {activeView === 'corridor' && <CorridorMap />}
          {activeView === 'kavach' && <KavachPanel />}
          {activeView === 'marl' && <MARLPanel />}
          {activeView === 'gate' && <GatePanel />}
          {activeView === 'zone' && <ZonePanel />}
          {activeView === 'health' && <HealthPanel />}
        </main>
      </div>
    </div>
  )
}
