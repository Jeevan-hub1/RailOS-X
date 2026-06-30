'use client'

import { useState, useEffect, useRef, useCallback, memo } from 'react'

const DIGITAL_TWIN_WS = process.env.NEXT_PUBLIC_DIGITAL_TWIN_WS || 'ws://localhost:3001/ws'
const DIGITAL_TWIN_REST = process.env.NEXT_PUBLIC_DIGITAL_TWIN_URL || 'http://localhost:3001'
const TOTAL_KM = 72

interface Train {
  id: string; name: string; trainClass: string; km: number
  speed: number; delay: number; status: string; direction: string; atStation: string | null
}
interface Defect {
  id: string; startKm: number; endKm: number; condition: string; label: string; severity: string; detectedAt: string
}
interface Signal { id: string; km: number; aspect: string }
interface Stats { activeTrains: number; onTimePct: number; trackAlerts: number; maxSpeed: number; totalDelayMin: number }
interface CorridorState { trains: Train[]; defects: Defect[]; signals: Signal[]; stats: Stats; timestamp: string }

const STATIONS = [
  { id: 'NDLS', name: 'New Delhi', km: 0 },
  { id: 'ANVT', name: 'Anand Vihar', km: 14 },
  { id: 'GZB', name: 'Ghaziabad', km: 27 },
  { id: 'MURN', name: 'Murad Nagar', km: 43 },
  { id: 'MODI', name: 'Modi Nagar', km: 54 },
  { id: 'MERT', name: 'Meerut', km: 72 },
] as const

// ── WebSocket hook ───────────────────────────────────────────────────────────
function useCorridorWS(onState: (s: CorridorState) => void) {
  const wsRef = useRef<WebSocket | null>(null)
  const mountedRef = useRef(true)
  const reconnectRef = useRef<ReturnType<typeof setTimeout>>()

  useEffect(() => {
    mountedRef.current = true
    let backoff = 1000
    function connect() {
      if (!mountedRef.current) return
      try {
        const ws = new WebSocket(DIGITAL_TWIN_WS)
        wsRef.current = ws
        ws.onopen = () => { backoff = 1000 }
        ws.onmessage = (evt) => {
          try {
            const msg = JSON.parse(evt.data)
            if (msg.type === 'state_update' && msg.data) onState(msg.data)
          } catch {}
        }
        ws.onclose = () => {
          if (mountedRef.current) { reconnectRef.current = setTimeout(connect, backoff); backoff = Math.min(backoff * 2, 10000) }
        }
        ws.onerror = () => ws.close()
      } catch {
        if (mountedRef.current) { reconnectRef.current = setTimeout(connect, backoff); backoff = Math.min(backoff * 2, 10000) }
      }
    }
    connect()
    return () => { mountedRef.current = false; clearTimeout(reconnectRef.current); wsRef.current?.close() }
  }, [onState])
}

// ── Sub-components ───────────────────────────────────────────────────────────
const StatCard = memo(function StatCard({ label, value, color }: { label: string; value: string | number; color: string }) {
  return (
    <div className="glass-panel p-3">
      <p className="text-[9px] uppercase tracking-wider text-slate-500">{label}</p>
      <p className={`text-2xl font-bold mt-0.5 ${color}`}>{value}</p>
    </div>
  )
})

const SignalDot = memo(function SignalDot({ signal }: { signal: Signal }) {
  const color = signal.aspect === 'green' ? 'bg-emerald-400' : signal.aspect === 'yellow' ? 'bg-amber-400' : 'bg-red-500'
  return (
    <div className="absolute top-1/2 translate-y-3 -translate-x-1/2"
      style={{ left: `calc(${(signal.km / TOTAL_KM) * 100}% * 0.88 + 5%)` }}
      title={`${signal.id} - ${signal.aspect.toUpperCase()}`}>
      <div className={`w-1.5 h-1.5 rounded-full ${color} ${signal.aspect === 'red' ? 'animate-pulse' : ''}`} />
    </div>
  )
})

const TrainMarker = memo(function TrainMarker({ train }: { train: Train }) {
  const statusClass = train.status === 'on-time' ? 'bg-emerald-600' :
    train.status === 'delayed' ? 'bg-amber-600' : 'bg-red-600 animate-pulse'
  const dirArrow = train.direction === 'UP' ? '\u2192' : '\u2190'
  return (
    <div className="absolute top-1/2 -translate-y-full -translate-x-1/2 group cursor-pointer z-10"
      style={{ left: `calc(${(train.km / TOTAL_KM) * 100}% * 0.88 + 5%)`, transition: 'left 1.2s linear' }}>
      <div className={`relative px-1.5 py-0.5 rounded text-[8px] font-bold text-white shadow-lg ${statusClass}`}>
        {dirArrow}{train.id.slice(-5)}
        <div className="absolute -bottom-1 left-1/2 -translate-x-1/2 w-1.5 h-1.5 rotate-45 bg-inherit" />
      </div>
      <div className="hidden group-hover:block absolute bottom-full left-1/2 -translate-x-1/2 mb-2 p-2.5 bg-slate-800 border border-slate-600 rounded-lg text-[10px] whitespace-nowrap z-20 shadow-xl">
        <p className="font-semibold text-white">{train.name}</p>
        <p className="text-slate-400">Class: {train.trainClass} | {train.direction}</p>
        <p className="text-slate-400">Speed: {train.speed} km/h | km {train.km}</p>
        {train.delay > 0 && <p className="text-amber-400">Delay: +{train.delay} min</p>}
        {train.atStation && <p className="text-sky-400">At: {train.atStation}</p>}
      </div>
    </div>
  )
})

const DefectOverlay = memo(function DefectOverlay({ defect }: { defect: Defect }) {
  const color = defect.condition === 'defect' ? 'bg-red-500/70 animate-pulse' : 'bg-amber-500/50'
  return (
    <div className={`absolute top-0 h-full rounded-full ${color}`}
      style={{ left: `${(defect.startKm / TOTAL_KM) * 100}%`, width: `${((defect.endKm - defect.startKm) / TOTAL_KM) * 100}%` }}
      title={`${defect.label} (${defect.severity})`} />
  )
})

// ── Main Component ───────────────────────────────────────────────────────────
export function CorridorMap() {
  const [trains, setTrains] = useState<Train[]>([])
  const [defects, setDefects] = useState<Defect[]>([])
  const [signals, setSignals] = useState<Signal[]>([])
  const [stats, setStats] = useState<Stats>({ activeTrains: 0, onTimePct: 0, trackAlerts: 0, maxSpeed: 0, totalDelayMin: 0 })
  const [connected, setConnected] = useState(false)
  const [lastUpdate, setLastUpdate] = useState('')

  const handleState = useCallback((state: CorridorState) => {
    setConnected(true)
    if (state.trains) setTrains(state.trains)
    if (state.defects) setDefects(state.defects)
    if (state.signals) setSignals(state.signals)
    if (state.stats) setStats(state.stats)
    if (state.timestamp) setLastUpdate(state.timestamp)
  }, [])

  useCorridorWS(handleState)

  // Fallback: if no WS data after 2s, run local simulation
  const simRef = useRef<ReturnType<typeof setInterval>>()
  useEffect(() => {
    const timer = setTimeout(() => {
      if (!connected) {
        // Try REST first
        fetch(`${DIGITAL_TWIN_REST}/api/v1/state`).then(r => r.json()).then(handleState).catch(() => {
          // No backend — run local simulation
          const localTrains: Train[] = [
            { id: 'T-12301', name: 'Rajdhani Exp', trainClass: 'Rajdhani', km: 18, speed: 130, delay: 0, status: 'on-time', direction: 'UP', atStation: null },
            { id: 'T-12002', name: 'Shatabdi Exp', trainClass: 'Shatabdi', km: 45, speed: 110, delay: 5, status: 'delayed', direction: 'UP', atStation: null },
            { id: 'T-22436', name: 'Vande Bharat', trainClass: 'Vande-Bharat', km: 62, speed: 160, delay: 0, status: 'on-time', direction: 'DN', atStation: null },
            { id: 'T-12909', name: 'Garib Rath', trainClass: 'Garib-Rath', km: 8, speed: 80, delay: 12, status: 'alert', direction: 'UP', atStation: null },
            { id: 'T-12213', name: 'Duronto Exp', trainClass: 'Duronto', km: 33, speed: 120, delay: 2, status: 'on-time', direction: 'UP', atStation: null },
            { id: 'T-12055', name: 'Jan Shatabdi', trainClass: 'Jan-Shatabdi', km: 55, speed: 110, delay: 0, status: 'on-time', direction: 'DN', atStation: null },
          ]
          const localDefects: Defect[] = [
            { id: 'def-001', startKm: 38, endKm: 42, condition: 'warning', label: 'Vibration anomaly', severity: 'MEDIUM', detectedAt: '' },
            { id: 'def-002', startKm: 55, endKm: 57, condition: 'defect', label: 'Rail crack detected', severity: 'HIGH', detectedAt: '' },
          ]
          setTrains(localTrains)
          setDefects(localDefects)
          setSignals(STATIONS.map((s, i) => ({ id: `sig-${i}`, km: s.km, aspect: 'green' })))
          setStats({ activeTrains: localTrains.length, onTimePct: 67, trackAlerts: 2, maxSpeed: 160, totalDelayMin: 19 })
          // Animate locally
          simRef.current = setInterval(() => {
            setTrains(prev => prev.map(t => {
              const dir = t.direction === 'UP' ? 1 : -1
              let newKm = t.km + (t.speed / 3600) * 1.5 * dir
              let newDir = t.direction
              if (newKm >= 72) { newKm = 72; newDir = 'DN' }
              if (newKm <= 0) { newKm = 0; newDir = 'UP' }
              return { ...t, km: Math.round(newKm * 100) / 100, direction: newDir }
            }))
          }, 1500)
        })
      }
    }, 2000)
    return () => { clearTimeout(timer); clearInterval(simRef.current) }
  }, [connected, handleState])

  return (
    <div className="space-y-5">
      {/* Stats Row */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <StatCard label="Active Trains" value={stats.activeTrains} color="text-sky-400" />
        <StatCard label="On-Time" value={`${stats.onTimePct}%`} color="text-emerald-400" />
        <StatCard label="Track Alerts" value={stats.trackAlerts} color="text-amber-400" />
        <StatCard label="Max Speed" value={`${Math.round(stats.maxSpeed)}`} color="text-white" />
        <StatCard label="Total Delay" value={`${stats.totalDelayMin}m`} color="text-red-400" />
      </div>

      {/* Multi-Track Corridor Visualization */}
      <div className="glass-panel p-5">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-white">NDLS — MERT Corridor (72 km)</h3>
            {connected && <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">{'\u25CF'} LIVE</span>}
          </div>
          <div className="flex items-center gap-4 text-[10px] text-slate-400">
            <span className="flex items-center gap-1"><span className="w-2.5 h-1 bg-emerald-400 rounded" /> Good</span>
            <span className="flex items-center gap-1"><span className="w-2.5 h-1 bg-amber-400 rounded" /> Warning</span>
            <span className="flex items-center gap-1"><span className="w-2.5 h-1 bg-red-400 rounded" /> Defect</span>
            <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-emerald-400" /> Signal</span>
            <span className="flex items-center gap-1 text-sky-400">&uarr; UP</span>
            <span className="flex items-center gap-1 text-purple-400">&darr; DN</span>
          </div>
        </div>

        {/* Track section labels */}
        <div className="flex items-center gap-0 mb-1 px-8 text-[8px] text-slate-600">
          <div style={{ width: '38%' }} className="text-center">4-TRACK (Quad)</div>
          <div style={{ width: '62%' }} className="text-center">2-TRACK (Double)</div>
        </div>

        {/* Multi-track visualization */}
        <div className="relative px-8" style={{ height: '180px' }}>
          {/* Track 1 - UP Fast (top) */}
          <div className="absolute left-8 right-8" style={{ top: '28%' }}>
            <div className="h-[3px] bg-slate-600 rounded-full relative">
              <div className="absolute -left-6 top-1/2 -translate-y-1/2 text-[7px] text-sky-400 font-mono">UP1</div>
              {defects.map(d => (
                <div key={`up1-${d.id}`} className={`absolute top-0 h-full rounded-full ${d.condition === 'defect' ? 'bg-red-500/60 animate-pulse' : 'bg-amber-500/40'}`}
                  style={{ left: `${(d.startKm / TOTAL_KM) * 100}%`, width: `${((d.endKm - d.startKm) / TOTAL_KM) * 100}%` }} />
              ))}
            </div>
          </div>

          {/* Track 2 - UP Slow */}
          <div className="absolute left-8 right-8" style={{ top: '40%' }}>
            <div className="h-[3px] bg-slate-700 rounded-full relative">
              <div className="absolute -left-6 top-1/2 -translate-y-1/2 text-[7px] text-sky-300/60 font-mono">UP2</div>
              {/* Quad section indicator (NDLS to GZB only) */}
              <div className="absolute top-0 h-full bg-sky-500/10 rounded-full" style={{ left: '0%', width: '37.5%' }} />
            </div>
          </div>

          {/* Track 3 - DN Slow */}
          <div className="absolute left-8 right-8" style={{ top: '58%' }}>
            <div className="h-[3px] bg-slate-700 rounded-full relative">
              <div className="absolute -left-6 top-1/2 -translate-y-1/2 text-[7px] text-purple-300/60 font-mono">DN2</div>
              <div className="absolute top-0 h-full bg-purple-500/10 rounded-full" style={{ left: '0%', width: '37.5%' }} />
            </div>
          </div>

          {/* Track 4 - DN Fast (bottom) */}
          <div className="absolute left-8 right-8" style={{ top: '70%' }}>
            <div className="h-[3px] bg-slate-600 rounded-full relative">
              <div className="absolute -left-6 top-1/2 -translate-y-1/2 text-[7px] text-purple-400 font-mono">DN1</div>
              {defects.map(d => (
                <div key={`dn1-${d.id}`} className={`absolute top-0 h-full rounded-full ${d.condition === 'defect' ? 'bg-red-500/60 animate-pulse' : 'bg-amber-500/40'}`}
                  style={{ left: `${(d.startKm / TOTAL_KM) * 100}%`, width: `${((d.endKm - d.startKm) / TOTAL_KM) * 100}%` }} />
              ))}
            </div>
          </div>

          {/* Quad/Double boundary marker at GZB (km 27) */}
          <div className="absolute top-[20%] bottom-[15%] border-l border-dashed border-slate-600/50"
            style={{ left: `calc(${(27 / TOTAL_KM) * 100}% * 0.88 + 5% + 32px)` }}>
            <span className="absolute -top-4 left-1 text-[7px] text-slate-600">4&rarr;2</span>
          </div>

          {/* Signals on UP track */}
          {signals.map(sig => {
            const color = sig.aspect === 'green' ? 'bg-emerald-400' : sig.aspect === 'yellow' ? 'bg-amber-400' : 'bg-red-500'
            return (
              <div key={sig.id} className="absolute -translate-x-1/2" style={{ left: `calc(${(sig.km / TOTAL_KM) * 100}% * 0.88 + 5% + 32px)`, top: '20%' }}>
                <div className={`w-1.5 h-1.5 rounded-full ${color} ${sig.aspect === 'red' ? 'animate-pulse' : ''}`}
                  title={`${sig.id} ${sig.aspect.toUpperCase()}`} />
              </div>
            )
          })}

          {/* Stations — spanning all tracks */}
          {STATIONS.map(stn => (
            <div key={stn.id} className="absolute -translate-x-1/2 flex flex-col items-center"
              style={{ left: `calc(${(stn.km / TOTAL_KM) * 100}% * 0.88 + 5% + 32px)`, top: '22%', height: '56%' }}>
              {/* Station block spanning tracks */}
              <div className="w-4 h-full bg-slate-500/20 border border-slate-500/30 rounded-sm" />
              <span className="text-[9px] text-slate-400 mt-1 font-semibold whitespace-nowrap">{stn.id}</span>
            </div>
          ))}

          {/* Trains positioned on their respective tracks */}
          {trains.map(train => {
            const isUp = train.direction === 'UP'
            // Assign track: fast trains on track 1, slower on track 2
            const isFast = ['Rajdhani', 'Shatabdi', 'Vande-Bharat', 'Duronto'].includes(train.trainClass)
            let trackTop: string
            if (isUp) {
              trackTop = isFast ? '22%' : '34%'
            } else {
              trackTop = isFast ? '64%' : '52%'
            }
            const statusClass = train.status === 'on-time' ? 'bg-emerald-600' :
              train.status === 'delayed' ? 'bg-amber-600' : 'bg-red-600 animate-pulse'
            const borderColor = isUp ? 'border-sky-500/50' : 'border-purple-500/50'

            return (
              <div key={train.id} className="absolute -translate-x-1/2 group cursor-pointer z-10"
                style={{ left: `calc(${(train.km / TOTAL_KM) * 100}% * 0.88 + 5% + 32px)`, top: trackTop, transition: 'left 1.2s linear, top 0.5s ease' }}>
                <div className={`relative px-1 py-0.5 rounded text-[7px] font-bold text-white shadow-lg border ${statusClass} ${borderColor}`}>
                  {isUp ? '\u25B6' : '\u25C0'}{train.id.slice(-5)}
                </div>
                {/* Tooltip */}
                <div className="hidden group-hover:block absolute bottom-full left-1/2 -translate-x-1/2 mb-1 p-2 bg-slate-800 border border-slate-600 rounded-lg text-[9px] whitespace-nowrap z-20 shadow-xl">
                  <p className="font-semibold text-white">{train.name}</p>
                  <p className="text-slate-400">{train.trainClass} | Track: {isUp ? 'UP' : 'DN'}{isFast ? '1' : '2'}</p>
                  <p className="text-slate-400">Speed: {train.speed} km/h | km {train.km}</p>
                  {train.delay > 0 && <p className="text-amber-400">Delay: +{train.delay} min</p>}
                  {train.atStation && <p className="text-sky-400">Halted at {train.atStation}</p>}
                </div>
              </div>
            )
          })}
        </div>

        {/* Track legend */}
        <div className="flex items-center justify-between px-8 mt-2">
          <div className="flex items-center gap-3 text-[8px] text-slate-500">
            <span>km 0</span>
            <span className="text-slate-600">|</span>
            <span>NDLS-GZB: 4 tracks (UP1, UP2, DN2, DN1)</span>
            <span className="text-slate-600">|</span>
            <span>GZB-MERT: 2 tracks (UP1, DN1)</span>
          </div>
          {lastUpdate && <p className="text-[8px] text-slate-600">Updated: {new Date(lastUpdate).toLocaleTimeString()}</p>}
        </div>
      </div>

      {/* Train Table + Defects side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Train Table */}
        <div className="lg:col-span-2 glass-panel p-4">
          <h3 className="text-sm font-semibold text-white mb-3">Active Trains</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-slate-500 border-b border-slate-800">
                  <th className="text-left py-1.5 px-2">Train</th>
                  <th className="text-left py-1.5 px-2">Class</th>
                  <th className="text-center py-1.5 px-2">Dir</th>
                  <th className="text-right py-1.5 px-2">Speed</th>
                  <th className="text-right py-1.5 px-2">Position</th>
                  <th className="text-right py-1.5 px-2">Delay</th>
                  <th className="text-center py-1.5 px-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {trains.map(t => (
                  <tr key={t.id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                    <td className="py-1.5 px-2">
                      <p className="font-mono text-sky-300">{t.id}</p>
                      <p className="text-[9px] text-slate-500">{t.name}</p>
                    </td>
                    <td className="py-1.5 px-2 text-white">{t.trainClass}</td>
                    <td className="py-1.5 px-2 text-center text-slate-400">{t.direction}</td>
                    <td className="py-1.5 px-2 text-right text-white font-mono">{t.speed} km/h</td>
                    <td className="py-1.5 px-2 text-right text-slate-300 font-mono">km {t.km}</td>
                    <td className="py-1.5 px-2 text-right">
                      {t.delay > 0 ? <span className="text-amber-400">+{t.delay}m</span> : <span className="text-emerald-400">0</span>}
                    </td>
                    <td className="py-1.5 px-2 text-center">
                      <span className={`inline-flex px-1.5 py-0.5 rounded text-[9px] font-semibold ${
                        t.status === 'on-time' ? 'bg-emerald-500/20 text-emerald-400' :
                        t.status === 'delayed' ? 'bg-amber-500/20 text-amber-400' :
                        'bg-red-500/20 text-red-400'}`}>
                        {t.atStation ? `@${t.atStation}` : t.status.toUpperCase()}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Defect Alerts */}
        <div className="glass-panel p-4">
          <h3 className="text-sm font-semibold text-white mb-3">Track Alerts ({defects.length})</h3>
          {defects.length === 0 ? (
            <p className="text-[10px] text-slate-600 text-center py-6">No active alerts</p>
          ) : (
            <div className="space-y-2 max-h-[300px] overflow-y-auto">
              {defects.map(d => (
                <div key={d.id} className={`p-2.5 rounded-lg border ${
                  d.condition === 'defect' ? 'border-red-500/30 bg-red-500/5' : 'border-amber-500/30 bg-amber-500/5'}`}>
                  <div className="flex items-center justify-between">
                    <p className="text-[10px] font-medium text-white">{d.label}</p>
                    <span className={`text-[8px] px-1.5 py-0.5 rounded font-bold ${
                      d.severity === 'HIGH' ? 'bg-red-500/20 text-red-400' :
                      d.severity === 'MEDIUM' ? 'bg-amber-500/20 text-amber-400' :
                      'bg-slate-700 text-slate-400'}`}>{d.severity}</span>
                  </div>
                  <p className="text-[9px] text-slate-500 mt-0.5">km {d.startKm} — km {d.endKm} | {d.id}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
