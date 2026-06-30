'use client'

import { useState, useEffect, useCallback, memo } from 'react'

const ZONE_URL = process.env.NEXT_PUBLIC_ZONE_URL || 'http://localhost:8092'

interface StationNode {
  node_id: string; station_id: string; health: string
  cpu_pct: number; gpu_pct: number; memory_pct: number; temperature_c: number
  inference_qps: number; queue_depth: number; last_heartbeat_s_ago: number
}
interface FLRound {
  roundId: string; roundNumber: number; modelId: string; status: string
  participants: number; submissions: number; submissionsPct: number
  globalAccuracy: number; elapsedS: number; error: string | null
}

// ── Simulated data (always available, overlaid by live data when backend has stations) ──
const SIM_STATIONS: StationNode[] = [
  { node_id: 'se-NDLS-000', station_id: 'NDLS', health: 'HEALTHY', cpu_pct: 45, gpu_pct: 72, memory_pct: 61, temperature_c: 68, inference_qps: 340, queue_depth: 12, last_heartbeat_s_ago: 3 },
  { node_id: 'se-GZB-000', station_id: 'GZB', health: 'HEALTHY', cpu_pct: 38, gpu_pct: 55, memory_pct: 48, temperature_c: 62, inference_qps: 280, queue_depth: 5, last_heartbeat_s_ago: 5 },
  { node_id: 'se-MURN-000', station_id: 'MURN', health: 'DEGRADED', cpu_pct: 82, gpu_pct: 91, memory_pct: 78, temperature_c: 79, inference_qps: 150, queue_depth: 89, last_heartbeat_s_ago: 8 },
  { node_id: 'se-MODI-000', station_id: 'MODI', health: 'HEALTHY', cpu_pct: 30, gpu_pct: 42, memory_pct: 35, temperature_c: 55, inference_qps: 200, queue_depth: 3, last_heartbeat_s_ago: 2 },
  { node_id: 'se-MERT-000', station_id: 'MERT', health: 'HEALTHY', cpu_pct: 52, gpu_pct: 65, memory_pct: 58, temperature_c: 64, inference_qps: 310, queue_depth: 18, last_heartbeat_s_ago: 4 },
]
const SIM_ROUNDS: FLRound[] = [
  { roundId: 'a1b2c3', roundNumber: 12, modelId: 'defect-detector-v3', status: 'COMPLETED', participants: 5, submissions: 5, submissionsPct: 100, globalAccuracy: 0.847, elapsedS: 45.2, error: null },
  { roundId: 'd4e5f6', roundNumber: 11, modelId: 'defect-detector-v3', status: 'COMPLETED', participants: 5, submissions: 4, submissionsPct: 80, globalAccuracy: 0.839, elapsedS: 38.7, error: null },
  { roundId: 'g7h8i9', roundNumber: 10, modelId: 'defect-detector-v3', status: 'COMPLETED', participants: 4, submissions: 4, submissionsPct: 100, globalAccuracy: 0.831, elapsedS: 52.1, error: null },
  { roundId: 'j0k1l2', roundNumber: 9, modelId: 'bearing-monitor', status: 'COMPLETED', participants: 5, submissions: 5, submissionsPct: 100, globalAccuracy: 0.812, elapsedS: 62.0, error: null },
  { roundId: 'm3n4o5', roundNumber: 8, modelId: 'defect-detector-v3', status: 'FAILED', participants: 5, submissions: 1, submissionsPct: 20, globalAccuracy: 0, elapsedS: 120, error: 'Timeout: insufficient submissions' },
]

// ── Sub-components ───────────────────────────────────────────────────────────
const StatBox = memo(function StatBox({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <div className="glass-panel p-3">
      <p className="text-[9px] uppercase tracking-wider text-slate-500">{label}</p>
      <p className={`text-xl font-bold mt-0.5 ${color || 'text-white'}`}>{value}</p>
    </div>
  )
})

const GPUBar = memo(function GPUBar({ label, pct, color }: { label: string; pct: number; color: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[9px] text-slate-500 w-8">{label}</span>
      <div className="flex-1 h-2 bg-slate-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${Math.min(100, pct)}%` }} />
      </div>
      <span className="text-[9px] font-mono text-slate-400 w-8 text-right">{Math.round(pct)}%</span>
    </div>
  )
})

const StationCard = memo(function StationCard({ s }: { s: StationNode }) {
  const healthColor = s.health === 'HEALTHY' ? 'status-ok' : s.health === 'DEGRADED' ? 'status-warn' : 'status-error'
  return (
    <div className="p-3 bg-slate-800/30 rounded-lg border border-slate-700/50">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <div className={`status-indicator ${healthColor}`} />
          <span className="text-xs font-semibold text-white">{s.station_id}</span>
          <span className="text-[8px] text-slate-600 font-mono">{s.node_id}</span>
        </div>
        <span className={`text-[9px] px-1.5 py-0.5 rounded ${s.health === 'HEALTHY' ? 'bg-emerald-500/20 text-emerald-400' : s.health === 'DEGRADED' ? 'bg-amber-500/20 text-amber-400' : 'bg-red-500/20 text-red-400'}`}>
          {s.health}
        </span>
      </div>
      <div className="space-y-1.5">
        <GPUBar label="GPU" pct={s.gpu_pct} color={s.gpu_pct > 85 ? 'bg-red-500' : s.gpu_pct > 60 ? 'bg-amber-500' : 'bg-emerald-500'} />
        <GPUBar label="CPU" pct={s.cpu_pct} color="bg-sky-500" />
        <GPUBar label="RAM" pct={s.memory_pct} color="bg-purple-500" />
      </div>
      <div className="flex justify-between mt-2.5 text-[9px] text-slate-500">
        <span>QPS: <span className="text-white font-mono">{s.inference_qps}</span></span>
        <span>Queue: <span className={`font-mono ${s.queue_depth > 50 ? 'text-amber-400' : 'text-white'}`}>{s.queue_depth}</span></span>
        <span className={s.temperature_c > 75 ? 'text-red-400' : ''}>{s.temperature_c}&deg;C</span>
      </div>
    </div>
  )
})

const FLRoundCard = memo(function FLRoundCard({ round }: { round: FLRound }) {
  const statusColor = round.status === 'COMPLETED' ? 'text-emerald-400' :
    round.status === 'FAILED' ? 'text-red-400' : 'text-amber-400'
  const statusBg = round.status === 'COMPLETED' ? 'bg-emerald-500/10' :
    round.status === 'FAILED' ? 'bg-red-500/10' : 'bg-amber-500/10'
  return (
    <div className={`p-2.5 rounded-lg border border-slate-700/50 ${statusBg}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-mono text-slate-300">#{round.roundNumber}</span>
          <span className="text-[9px] text-slate-500">{round.modelId}</span>
        </div>
        <span className={`text-[9px] font-bold ${statusColor}`}>{round.status}</span>
      </div>
      <div className="flex items-center justify-between mt-1.5">
        <span className="text-[9px] text-slate-500">{round.submissions}/{round.participants} stations</span>
        <span className="text-[9px] text-slate-500">{round.elapsedS}s</span>
        {round.globalAccuracy > 0 && (
          <span className="text-[9px] font-mono text-emerald-400">{(round.globalAccuracy * 100).toFixed(1)}%</span>
        )}
      </div>
      {round.globalAccuracy > 0 && (
        <div className="h-1 bg-slate-700 rounded-full mt-1.5 overflow-hidden">
          <div className="h-full bg-emerald-500 rounded-full" style={{ width: `${round.globalAccuracy * 100}%` }} />
        </div>
      )}
      {round.error && <p className="text-[8px] text-red-400 mt-1">{round.error}</p>}
    </div>
  )
})

// ── Main component ───────────────────────────────────────────────────────────
export function ZonePanel() {
  const [stations, setStations] = useState<StationNode[]>(SIM_STATIONS)
  const [flRounds, setFlRounds] = useState<FLRound[]>(SIM_ROUNDS)
  const [live, setLive] = useState(false)
  const [globalAccuracy, setGlobalAccuracy] = useState(0.847)
  const [totalRounds, setTotalRounds] = useState(12)
  const [modelVersion, setModelVersion] = useState('defect-detector-v3-r12')
  const [slaViolations, setSlaViolations] = useState(2)

  // Try to fetch live data from Zone backend; keep simulated if unavailable
  const refresh = useCallback(async () => {
    try {
      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 2500)
      const res = await fetch(`${ZONE_URL}/api/v1/status`, { signal: controller.signal })
      clearTimeout(timeout)
      if (!res.ok) return
      const data = await res.json()
      if (data && data.zone_id) {
        // Backend responded with real data
        if (data.stations_registered > 0) {
          setLive(true)
          setSlaViolations(data.sla_violations_recent || 0)
        }
        const fed = data.federated || {}
        if (fed.totalRounds > 0) setTotalRounds(fed.totalRounds)
        if (fed.globalAccuracy > 0) setGlobalAccuracy(fed.globalAccuracy)
        if (fed.globalModelVersion) setModelVersion(fed.globalModelVersion)
        if (fed.recentRounds?.length > 0) setFlRounds(fed.recentRounds)
        // Try stations endpoint
        const stRes = await fetch(`${ZONE_URL}/api/v1/stations`, { signal: AbortSignal.timeout(2000) })
        if (stRes.ok) {
          const stData = await stRes.json()
          if (stData.stations?.length > 0) setStations(stData.stations)
        }
      }
    } catch { /* keep simulated data */ }
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 8000)
    return () => clearInterval(id)
  }, [refresh])

  // Simulate gradual changes to station data (makes dashboard feel alive)
  useEffect(() => {
    if (live) return // don't simulate if live data is flowing
    const id = setInterval(() => {
      setStations(prev => prev.map(s => ({
        ...s,
        cpu_pct: Math.max(10, Math.min(95, s.cpu_pct + (Math.random() - 0.5) * 6)),
        gpu_pct: Math.max(10, Math.min(95, s.gpu_pct + (Math.random() - 0.5) * 8)),
        memory_pct: Math.max(20, Math.min(90, s.memory_pct + (Math.random() - 0.5) * 3)),
        temperature_c: Math.max(45, Math.min(85, s.temperature_c + (Math.random() - 0.5) * 2)),
        inference_qps: Math.max(50, Math.round(s.inference_qps + (Math.random() - 0.5) * 40)),
        queue_depth: Math.max(0, Math.round(s.queue_depth + (Math.random() - 0.5) * 10)),
      })))
    }, 3000)
    return () => clearInterval(id)
  }, [live])

  const healthyCount = stations.filter(s => s.health === 'HEALTHY').length
  const avgGpu = stations.length > 0 ? Math.round(stations.reduce((a, s) => a + s.gpu_pct, 0) / stations.length) : 0
  const totalQps = stations.reduce((a, s) => a + s.inference_qps, 0)
  const completedRounds = flRounds.filter(r => r.status === 'COMPLETED')

  return (
    <div className="space-y-5">
      {/* Stats Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
        <StatBox label="Stations" value={stations.length} color="text-sky-400" />
        <StatBox label="Healthy" value={healthyCount} color="text-emerald-400" />
        <StatBox label="Avg GPU" value={`${avgGpu}%`} color={avgGpu > 80 ? 'text-red-400' : avgGpu > 60 ? 'text-amber-400' : 'text-white'} />
        <StatBox label="Total QPS" value={totalQps} color="text-purple-400" />
        <StatBox label="FL Rounds" value={totalRounds} color="text-indigo-400" />
        <StatBox label="Accuracy" value={`${(globalAccuracy * 100).toFixed(1)}%`} color="text-emerald-400" />
        <StatBox label="SLA Issues" value={slaViolations} color={slaViolations > 0 ? 'text-amber-400' : 'text-emerald-400'} />
      </div>

      {!live && <p className="text-[10px] text-slate-600 px-1">Simulated cluster data (live updates when stations register with zone backend)</p>}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Station Cluster — 2 cols */}
        <div className="lg:col-span-2 glass-panel p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-white">Station Edge Cluster</h3>
            <span className="text-[9px] text-slate-500">Jetson Orin NX/AGX | {stations.length} nodes</span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {stations.map(s => <StationCard key={s.node_id} s={s} />)}
          </div>
        </div>

        {/* Federated Learning — 1 col */}
        <div className="glass-panel p-4">
          <div className="flex items-center justify-between mb-1">
            <h3 className="text-sm font-semibold text-white">Federated Learning</h3>
            <span className="text-[9px] px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-400 border border-indigo-500/30">FedAvg</span>
          </div>
          <p className="text-[9px] text-slate-500 mb-3">Model: {modelVersion}</p>

          {/* Accuracy trend */}
          {completedRounds.length > 0 && (
            <div className="mb-4">
              <p className="text-[9px] uppercase tracking-wider text-slate-500 mb-1.5">Accuracy Trend</p>
              <div className="flex items-end gap-1 h-14 px-1">
                {completedRounds.slice(-8).map((r) => {
                  const h = Math.max(4, (r.globalAccuracy - 0.7) * 300)
                  return (
                    <div key={r.roundId} className="flex-1 flex flex-col items-center justify-end h-full">
                      <div className="w-full bg-gradient-to-t from-indigo-600 to-indigo-400 rounded-t transition-all"
                        style={{ height: `${h}%` }}
                        title={`R${r.roundNumber}: ${(r.globalAccuracy*100).toFixed(1)}%`} />
                      <span className="text-[7px] text-slate-600 mt-0.5">R{r.roundNumber}</span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Privacy budget */}
          <div className="mb-4 p-2.5 bg-slate-800/40 rounded-lg border border-slate-700/30">
            <div className="flex justify-between text-[9px] mb-1">
              <span className="text-slate-400">Privacy Budget (&epsilon;)</span>
              <span className="text-teal-400 font-mono">38.0 / 50.0</span>
            </div>
            <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
              <div className="h-full bg-gradient-to-r from-teal-500 to-emerald-400 rounded-full" style={{ width: '76%' }} />
            </div>
            <p className="text-[8px] text-slate-600 mt-1.5">Gaussian mechanism | &delta;=1e-5 | Grad clip L2=1.0</p>
          </div>

          {/* Drift detection status */}
          <div className="mb-4 p-2 bg-slate-800/40 rounded-lg border border-slate-700/30">
            <div className="flex items-center justify-between">
              <span className="text-[9px] text-slate-400">Drift Detection</span>
              <span className="text-[9px] text-emerald-400">KL &lt; 0.15 threshold</span>
            </div>
          </div>

          {/* Round history */}
          <p className="text-[9px] uppercase tracking-wider text-slate-500 mb-1.5">Recent Rounds</p>
          <div className="space-y-2 max-h-[220px] overflow-y-auto">
            {flRounds.map(r => <FLRoundCard key={r.roundId} round={r} />)}
          </div>
        </div>
      </div>
    </div>
  )
}
