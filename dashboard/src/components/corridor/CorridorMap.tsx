'use client'

import { useState, useEffect } from 'react'

interface TrainPosition {
  id: string
  name: string
  km: number
  speed: number
  delay: number
  status: 'on-time' | 'delayed' | 'alert'
}

interface TrackSegment {
  id: string
  startKm: number
  endKm: number
  condition: 'good' | 'warning' | 'defect'
  label?: string
}

const STATIONS = [
  { name: 'New Delhi', short: 'NDLS', km: 0 },
  { name: 'Anand Vihar', short: 'ANVT', km: 14 },
  { name: 'Ghaziabad', short: 'GZB', km: 27 },
  { name: 'Murad Nagar', short: 'MURN', km: 43 },
  { name: 'Modi Nagar', short: 'MODI', km: 54 },
  { name: 'Meerut', short: 'MERT', km: 72 },
]

const TOTAL_KM = 72

export function CorridorMap() {
  const [trains, setTrains] = useState<TrainPosition[]>([
    { id: 'T-12301', name: 'Rajdhani Exp', km: 18, speed: 130, delay: 0, status: 'on-time' },
    { id: 'T-12002', name: 'Shatabdi Exp', km: 45, speed: 110, delay: 5, status: 'delayed' },
    { id: 'T-12213', name: 'Duronto Exp', km: 62, speed: 95, delay: 0, status: 'on-time' },
    { id: 'T-12909', name: 'Garib Rath', km: 8, speed: 80, delay: 12, status: 'alert' },
  ])

  const [segments] = useState<TrackSegment[]>([
    { id: 'seg-001', startKm: 38, endKm: 42, condition: 'warning', label: 'Vibration anomaly' },
    { id: 'seg-002', startKm: 55, endKm: 57, condition: 'defect', label: 'Rail crack detected' },
  ])

  // Simulate train movement
  useEffect(() => {
    const id = setInterval(() => {
      setTrains(prev => prev.map(t => ({
        ...t,
        km: t.km + (t.speed / 3600) * 2 > TOTAL_KM ? 0 : t.km + (t.speed / 3600) * 2,
      })))
    }, 2000)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="space-y-6">
      {/* Stats Row */}
      <div className="grid grid-cols-4 gap-4">
        <StatCard label="Active Trains" value="4" color="sky" />
        <StatCard label="On-Time" value="75%" color="emerald" />
        <StatCard label="Track Alerts" value="2" color="amber" />
        <StatCard label="Corridor Speed" value="130 km/h" color="slate" />
      </div>

      {/* Corridor Visualization */}
      <div className="glass-panel p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-white">NDLS — MERT Pilot Corridor (72 km)</h3>
          <div className="flex items-center gap-4 text-xs text-slate-400">
            <span className="flex items-center gap-1"><span className="w-3 h-1 bg-emerald-400 rounded" /> Good</span>
            <span className="flex items-center gap-1"><span className="w-3 h-1 bg-amber-400 rounded" /> Warning</span>
            <span className="flex items-center gap-1"><span className="w-3 h-1 bg-red-400 rounded" /> Defect</span>
          </div>
        </div>

        {/* Track Line */}
        <div className="relative h-32 mt-8">
          {/* Track background */}
          <div className="absolute left-8 right-8 top-1/2 h-2 bg-slate-700 rounded-full -translate-y-1/2">
            {/* Segment overlays */}
            {segments.map(seg => (
              <div
                key={seg.id}
                className={`absolute top-0 h-full rounded-full ${
                  seg.condition === 'defect' ? 'bg-red-500/80 animate-pulse' : 'bg-amber-500/60'
                }`}
                style={{
                  left: `${(seg.startKm / TOTAL_KM) * 100}%`,
                  width: `${((seg.endKm - seg.startKm) / TOTAL_KM) * 100}%`,
                }}
                title={seg.label}
              />
            ))}
          </div>

          {/* Stations */}
          {STATIONS.map(station => (
            <div
              key={station.short}
              className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 flex flex-col items-center"
              style={{ left: `calc(${(station.km / TOTAL_KM) * 100}% * 0.88 + 5%)` }}
            >
              <div className="w-3 h-3 rounded-full bg-slate-500 border-2 border-slate-400 mb-1" />
              <span className="text-[10px] text-slate-400 mt-4 font-medium">{station.short}</span>
            </div>
          ))}

          {/* Trains */}
          {trains.map(train => (
            <div
              key={train.id}
              className="absolute top-1/2 -translate-y-full -translate-x-1/2 group cursor-pointer"
              style={{ left: `calc(${(train.km / TOTAL_KM) * 100}% * 0.88 + 5%)` }}
            >
              <div className={`relative px-2 py-1 rounded text-[9px] font-bold text-white shadow-lg transition-all ${
                train.status === 'on-time' ? 'bg-emerald-600' :
                train.status === 'delayed' ? 'bg-amber-600' :
                'bg-red-600 animate-pulse'
              }`}>
                {train.id.slice(-5)}
                <div className="absolute -bottom-1 left-1/2 -translate-x-1/2 w-2 h-2 rotate-45 bg-inherit" />
              </div>
              {/* Tooltip */}
              <div className="hidden group-hover:block absolute bottom-full left-1/2 -translate-x-1/2 mb-2 p-2 bg-slate-800 border border-slate-600 rounded-lg text-xs whitespace-nowrap z-10">
                <p className="font-semibold text-white">{train.name}</p>
                <p className="text-slate-400">Speed: {train.speed} km/h</p>
                <p className="text-slate-400">Position: km {train.km.toFixed(1)}</p>
                {train.delay > 0 && <p className="text-amber-400">Delay: +{train.delay} min</p>}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Train Table */}
      <div className="glass-panel p-5">
        <h3 className="text-sm font-semibold text-white mb-4">Active Trains</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-slate-500 border-b border-slate-800">
                <th className="text-left py-2 px-3">Train</th>
                <th className="text-left py-2 px-3">Name</th>
                <th className="text-right py-2 px-3">Speed</th>
                <th className="text-right py-2 px-3">Position</th>
                <th className="text-right py-2 px-3">Delay</th>
                <th className="text-center py-2 px-3">Status</th>
              </tr>
            </thead>
            <tbody>
              {trains.map(train => (
                <tr key={train.id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                  <td className="py-2.5 px-3 font-mono text-sky-300">{train.id}</td>
                  <td className="py-2.5 px-3 text-white">{train.name}</td>
                  <td className="py-2.5 px-3 text-right text-slate-300">{train.speed} km/h</td>
                  <td className="py-2.5 px-3 text-right text-slate-300">km {train.km.toFixed(1)}</td>
                  <td className="py-2.5 px-3 text-right">
                    {train.delay > 0 ? <span className="text-amber-400">+{train.delay} min</span> : <span className="text-emerald-400">On time</span>}
                  </td>
                  <td className="py-2.5 px-3 text-center">
                    <span className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold ${
                      train.status === 'on-time' ? 'bg-emerald-500/20 text-emerald-400' :
                      train.status === 'delayed' ? 'bg-amber-500/20 text-amber-400' :
                      'bg-red-500/20 text-red-400'
                    }`}>
                      {train.status.toUpperCase()}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Defect Alerts */}
      <div className="glass-panel p-5">
        <h3 className="text-sm font-semibold text-white mb-3">Track Condition Alerts</h3>
        <div className="space-y-2">
          {segments.map(seg => (
            <div key={seg.id} className={`flex items-center gap-3 p-3 rounded-lg border ${
              seg.condition === 'defect' ? 'border-red-500/30 bg-red-500/5' : 'border-amber-500/30 bg-amber-500/5'
            }`}>
              <div className={`status-indicator ${seg.condition === 'defect' ? 'status-error' : 'status-warn'}`} />
              <div className="flex-1">
                <p className="text-xs font-medium text-white">{seg.label}</p>
                <p className="text-[10px] text-slate-500">km {seg.startKm} — km {seg.endKm} | Segment {seg.id}</p>
              </div>
              <span className={`text-[10px] px-2 py-0.5 rounded ${
                seg.condition === 'defect' ? 'bg-red-500/20 text-red-400' : 'bg-amber-500/20 text-amber-400'
              }`}>
                {seg.condition.toUpperCase()}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function StatCard({ label, value, color }: { label: string; value: string; color: string }) {
  const colorMap: Record<string, string> = {
    sky: 'text-sky-400',
    emerald: 'text-emerald-400',
    amber: 'text-amber-400',
    slate: 'text-white',
  }
  return (
    <div className="glass-panel p-4">
      <p className="text-[10px] uppercase tracking-wider text-slate-500">{label}</p>
      <p className={`text-2xl font-bold mt-1 ${colorMap[color]}`}>{value}</p>
    </div>
  )
}
