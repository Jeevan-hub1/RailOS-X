'use client'

import { useState } from 'react'
import { Sidebar } from '@/components/ui/Sidebar'
import { Header } from '@/components/ui/Header'
import { CorridorMap } from '@/components/corridor/CorridorMap'
import { KavachPanel } from '@/components/kavach/KavachPanel'
import { MARLPanel } from '@/components/marl/MARLPanel'
import { GatePanel } from '@/components/gate/GatePanel'
import { HealthPanel } from '@/components/health/HealthPanel'

type View = 'corridor' | 'kavach' | 'marl' | 'gate' | 'health'

export default function Dashboard() {
  const [activeView, setActiveView] = useState<View>('corridor')

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
          {activeView === 'health' && <HealthPanel />}
        </main>
      </div>
    </div>
  )
}
