'use client'

import { useState, useCallback, useRef, memo } from 'react'
import { getKavachAdvisory, type KavachAdvisory } from '@/lib/api'

const TRAIN_TYPES = [
  { value: 'vande_bharat', label: 'Vande Bharat (EMU, 430t)' },
  { value: 'wap7_rajdhani', label: 'WAP-7 Rajdhani (980t)' },
  { value: 'wdp4d_mail', label: 'WDP-4D Mail/Express (1400t)' },
  { value: 'default', label: 'Generic (580t)' },
] as const

// ── Memoized sub-components ──────────────────────────────────────────────────
const ParamBox = memo(function ParamBox({ label, value, mono, color }: { label: string; value: string; mono?: boolean; color?: string }) {
  return (
    <div className="p-2.5 bg-slate-800/50 rounded-lg">
      <p className="text-[10px] text-slate-500 uppercase">{label}</p>
      <p className={`text-sm mt-0.5 ${mono ? 'font-mono' : ''} ${color || 'text-white'}`}>{value}</p>
    </div>
  )
})

const PhaseBar = memo(function PhaseBar({ label, value, total, color }: { label: string; value: number; total: number; color: string }) {
  const pct = total > 0 ? (value / total) * 100 : 0
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] text-slate-500 w-20 text-right">{label}</span>
      <div className="flex-1 h-3 bg-slate-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-500 ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] text-white font-mono w-14 text-right">{value.toFixed(0)} m</span>
    </div>
  )
})

const Slider = memo(function Slider({ label, value, min, max, step, unit, color, onChange }: {
  label: string; value: number; min: number; max: number; step: number; unit: string; color: string; onChange: (v: number) => void
}) {
  return (
    <div className="mb-5">
      <div className="flex justify-between text-xs mb-1.5">
        <span className="text-slate-400">{label}</span>
        <span className={`font-mono font-bold ${color}`}>{value}{step < 1 ? value.toFixed(1) : value} {unit}</span>
      </div>
      <input
        type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full h-2 rounded-full appearance-none cursor-pointer bg-slate-700 accent-sky-500"
      />
    </div>
  )
})

// ── Main component ───────────────────────────────────────────────────────────
export function KavachPanel() {
  // Physics inputs
  const [speed, setSpeed] = useState(120)
  const [vibration, setVibration] = useState(1.5)
  const [humidity, setHumidity] = useState(50)
  const [headwind, setHeadwind] = useState(0)
  const [ambientTemp, setAmbientTemp] = useState(35)
  const [trainType, setTrainType] = useState('vande_bharat')

  // Results
  const [result, setResult] = useState<KavachAdvisory | null>(null)
  const [loading, setLoading] = useState(false)
  const [history, setHistory] = useState<KavachAdvisory[]>([])

  const abortRef = useRef<AbortController | null>(null)

  const computeAdvisory = useCallback(async () => {
    abortRef.current?.abort()
    abortRef.current = new AbortController()
    setLoading(true)
    try {
      const data = await getKavachAdvisory({
        speed_kmh: speed, lat: 28.6139, lon: 77.2090,
        vibration_rms: vibration, humidity_pct: humidity,
        headwind_kmh: headwind, ambient_temp_c: ambientTemp,
        train_type: trainType,
      })
      if ('alertType' in data) {
        setResult(data as KavachAdvisory)
        setHistory(prev => [data as KavachAdvisory, ...prev].slice(0, 10))
      }
    } catch (e) {
      if ((e as Error).name !== 'AbortError') console.error('Kavach API error:', e)
    }
    setLoading(false)
  }, [speed, vibration, humidity, headwind, ambientTemp, trainType])

  const phases = result?.brakingPhases
  const totalDist = result?.advisoryStoppingDist_m || 0

  return (
    <div className="space-y-5">
      {/* Safety Banner */}
      <div className="glass-panel p-3 border-amber-500/30 bg-amber-500/5">
        <div className="flex items-center gap-3">
          <span className="text-xl">&#9888;&#65039;</span>
          <div>
            <p className="text-sm font-semibold text-amber-300">ADVISORY ONLY — NOT CERTIFIED</p>
            <p className="text-[11px] text-slate-400">Read-only overlay on Kavach 4.0. Polach adhesion model + multi-phase braking + Davis drag + brake fade. Hardware data diode enforced.</p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* ── Column 1: Controls ──────────────────────────────────────────── */}
        <div className="glass-panel p-5">
          <h3 className="text-sm font-semibold text-white mb-4">Physics Inputs</h3>

          <Slider label="Train Speed" value={speed} min={0} max={200} step={5} unit="km/h" color="text-sky-400" onChange={setSpeed} />
          <Slider label="Bogie Vibration (RMS)" value={vibration} min={0} max={5} step={0.1} unit="g" color="text-purple-400" onChange={setVibration} />
          <Slider label="Humidity" value={humidity} min={20} max={100} step={5} unit="%" color="text-teal-400" onChange={setHumidity} />
          <Slider label="Headwind" value={headwind} min={-30} max={60} step={5} unit="km/h" color="text-cyan-400" onChange={setHeadwind} />
          <Slider label="Ambient Temp" value={ambientTemp} min={10} max={55} step={1} unit="C" color="text-orange-400" onChange={setAmbientTemp} />

          {/* Train Type Selector */}
          <div className="mb-5">
            <label className="text-xs text-slate-400 mb-1.5 block">Train Composition</label>
            <select value={trainType} onChange={(e) => setTrainType(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white">
              {TRAIN_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </div>

          {/* Fixed GPS */}
          <div className="grid grid-cols-2 gap-2 mb-4 p-2.5 bg-slate-800/50 rounded-lg">
            <div className="text-[11px]"><span className="text-slate-500">Lat</span><p className="text-white font-mono">28.6139</p></div>
            <div className="text-[11px]"><span className="text-slate-500">Lon</span><p className="text-white font-mono">77.2090</p></div>
          </div>

          <button onClick={computeAdvisory} disabled={loading}
            className="w-full py-3 rounded-lg bg-gradient-to-r from-sky-600 to-blue-700 text-white font-semibold text-sm hover:from-sky-500 hover:to-blue-600 disabled:opacity-50 transition-all shadow-lg shadow-sky-500/20">
            {loading ? 'Computing...' : 'Compute Braking Advisory'}
          </button>
          {result && <p className="text-[10px] text-slate-600 mt-2 text-center">Computed in {result.computeLatencyMs} ms</p>}
        </div>

        {/* ── Column 2: Braking Phases ────────────────────────────────────── */}
        <div className="glass-panel p-5">
          <h3 className="text-sm font-semibold text-white mb-4">Multi-Phase Braking</h3>

          {result && phases ? (
            <div className="space-y-5">
              {/* Total distance hero */}
              <div className="text-center p-4 bg-slate-800/60 rounded-xl">
                <p className="text-[10px] uppercase tracking-wider text-slate-500">Total Stopping Distance</p>
                <p className="text-4xl font-bold text-sky-400 mt-1">{totalDist.toFixed(0)}<span className="text-lg text-slate-400 ml-1">m</span></p>
                <p className="text-[10px] text-slate-500 mt-1">{phases.totalTime_s.toFixed(1)}s total | Peak {phases.peakDecel_ms2.toFixed(2)} m/s&sup2;</p>
              </div>

              {/* Phase breakdown bars */}
              <div className="space-y-2.5">
                <p className="text-[10px] uppercase tracking-wider text-slate-500">Phase Breakdown</p>
                <PhaseBar label="Reaction" value={phases.reactionDist_m} total={totalDist} color="bg-yellow-500" />
                <PhaseBar label="Propagation" value={phases.propagationDist_m} total={totalDist} color="bg-orange-500" />
                <PhaseBar label="Braking" value={phases.brakingDist_m} total={totalDist} color="bg-sky-500" />
              </div>

              {/* Brake fade indicator */}
              <div className="flex items-center gap-2 p-2.5 rounded-lg bg-slate-800/40">
                <span className="text-[10px] text-slate-500">Brake Fade</span>
                <div className="flex-1 h-2 bg-slate-700 rounded-full overflow-hidden">
                  <div className={`h-full rounded-full transition-all duration-500 ${phases.brakeFade > 0.9 ? 'bg-emerald-500' : phases.brakeFade > 0.7 ? 'bg-amber-500' : 'bg-red-500'}`}
                    style={{ width: `${phases.brakeFade * 100}%` }} />
                </div>
                <span className="text-[10px] font-mono text-white">{(phases.brakeFade * 100).toFixed(1)}%</span>
              </div>

              {/* Safety invariant */}
              <div className={`p-3 rounded-lg border ${
                result.safetyInvariant.satisfied ? 'border-emerald-500/30 bg-emerald-500/5' : 'border-red-500/30 bg-red-500/5'
              }`}>
                <div className="flex items-center gap-2">
                  <span className="text-lg">{result.safetyInvariant.satisfied ? '\u2705' : '\u274C'}</span>
                  <div>
                    <p className="text-xs font-semibold text-white">Safety Invariant: advisory &ge; certified</p>
                    <p className="text-[10px] text-slate-400">
                      Margin: +{result.safetyInvariant.marginPct}%
                      {result.safetyInvariant.clamped && <span className="text-amber-400 ml-2">(clamped to certified)</span>}
                    </p>
                  </div>
                </div>
              </div>

              {/* Certified comparison */}
              <div className="p-3 bg-slate-800/40 rounded-lg">
                <p className="text-[10px] text-slate-500 mb-2">Certified vs Advisory</p>
                <div className="flex items-end gap-4">
                  <div className="flex-1">
                    <div className="h-16 flex items-end">
                      <div className="w-full bg-amber-500/30 border border-amber-500/50 rounded-t"
                        style={{ height: `${Math.min(100, (result.certifiedStoppingDist_m / Math.max(totalDist, result.certifiedStoppingDist_m)) * 100)}%` }} />
                    </div>
                    <p className="text-[9px] text-amber-400 text-center mt-1">Certified</p>
                    <p className="text-[10px] text-white text-center font-mono">{result.certifiedStoppingDist_m.toFixed(0)}m</p>
                  </div>
                  <div className="flex-1">
                    <div className="h-16 flex items-end">
                      <div className="w-full bg-sky-500/30 border border-sky-500/50 rounded-t"
                        style={{ height: `${Math.min(100, (totalDist / Math.max(totalDist, result.certifiedStoppingDist_m)) * 100)}%` }} />
                    </div>
                    <p className="text-[9px] text-sky-400 text-center mt-1">Advisory</p>
                    <p className="text-[10px] text-white text-center font-mono">{totalDist.toFixed(0)}m</p>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-64 text-slate-600">
              <span className="text-4xl mb-3">&#x1F6E4;&#xFE0F;</span>
              <p className="text-sm">Compute to see phase breakdown</p>
              <p className="text-[10px] mt-1 text-center max-w-48">Reaction + propagation + full braking with Polach adhesion model</p>
            </div>
          )}
        </div>

        {/* ── Column 3: Physics Details ───────────────────────────────────── */}
        <div className="glass-panel p-5">
          <h3 className="text-sm font-semibold text-white mb-4">Physics Parameters</h3>

          {result ? (
            <div className="space-y-4">
              {/* Adhesion model */}
              <div>
                <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Polach Adhesion</p>
                <div className="flex items-center gap-2 mb-2">
                  <div className="flex-1 h-3 bg-slate-700 rounded-full overflow-hidden">
                    <div className="h-full bg-gradient-to-r from-red-500 via-amber-500 to-emerald-500 rounded-full"
                      style={{ width: `${(result.adhesionCoeff / 0.40) * 100}%` }} />
                  </div>
                  <span className="text-xs font-mono text-white">&mu;={result.adhesionCoeff}</span>
                </div>
                <div className="grid grid-cols-3 gap-1 text-[9px] text-slate-500">
                  <span>0.02 (ice)</span>
                  <span className="text-center">0.20 (wet)</span>
                  <span className="text-right">0.40 (dry)</span>
                </div>
              </div>

              {/* Parameters grid */}
              <div className="grid grid-cols-2 gap-2">
                <ParamBox label="Adhesion" value={`${result.adhesionCoeff}`} mono color="text-emerald-400" />
                <ParamBox label="Train" value={result.trainType.replace(/_/g, ' ')} />
                <ParamBox label="Gradient" value={`${result.gradientRad.toFixed(4)} rad`} mono />
                <ParamBox label="Curve R" value={result.curveRadiusM > 0 ? `${result.curveRadiusM}m` : 'Straight'} />
                <ParamBox label="Peak Decel" value={`${result.brakingPhases.peakDecel_ms2} m/s\u00B2`} mono color="text-sky-400" />
                <ParamBox label="Brake Fade" value={`${(result.brakingPhases.brakeFade * 100).toFixed(1)}%`} color={result.brakingPhases.brakeFade > 0.9 ? 'text-emerald-400' : 'text-amber-400'} />
              </div>

              {/* Environment summary */}
              <div>
                <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Environment</p>
                <div className="grid grid-cols-3 gap-2">
                  <div className="p-2 bg-slate-800/50 rounded text-center">
                    <p className="text-[9px] text-slate-500">Humidity</p>
                    <p className="text-xs text-teal-400 font-mono">{result.environment.humidityPct}%</p>
                  </div>
                  <div className="p-2 bg-slate-800/50 rounded text-center">
                    <p className="text-[9px] text-slate-500">Wind</p>
                    <p className="text-xs text-cyan-400 font-mono">{result.environment.headwindKmh} km/h</p>
                  </div>
                  <div className="p-2 bg-slate-800/50 rounded text-center">
                    <p className="text-[9px] text-slate-500">Temp</p>
                    <p className="text-xs text-orange-400 font-mono">{result.environment.ambientTempC}&deg;C</p>
                  </div>
                </div>
              </div>

              {/* Physics model info */}
              <div className="p-3 bg-slate-800/30 rounded-lg border border-slate-700/50">
                <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Model</p>
                <p className="text-[10px] text-slate-400 leading-relaxed">
                  Polach creep force adhesion &bull; Davis resistance (RDSO) &bull;
                  Multi-phase decel (reaction + propagation + full) &bull;
                  Rotational inertia &lambda; &bull; Thermal brake fade &bull;
                  Aerodynamic drag (C<sub>d</sub>A)
                </p>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-64 text-slate-600">
              <span className="text-4xl mb-3">&#x2699;&#xFE0F;</span>
              <p className="text-sm">Physics details will appear here</p>
              <p className="text-[10px] mt-1 text-center max-w-48">Polach adhesion, Davis drag, rotational inertia, brake fade</p>
            </div>
          )}
        </div>
      </div>

      {/* History */}
      {history.length > 0 && (
        <div className="glass-panel p-4">
          <h3 className="text-sm font-semibold text-white mb-3">Advisory History</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-slate-500 border-b border-slate-800">
                  <th className="text-left py-1.5 px-2">Time</th>
                  <th className="text-right py-1.5 px-2">Speed</th>
                  <th className="text-right py-1.5 px-2">Advisory</th>
                  <th className="text-right py-1.5 px-2">Certified</th>
                  <th className="text-right py-1.5 px-2">&mu;</th>
                  <th className="text-right py-1.5 px-2">Fade</th>
                  <th className="text-center py-1.5 px-2">Safe</th>
                </tr>
              </thead>
              <tbody>
                {history.map((h, i) => (
                  <tr key={`${h.alertId}-${i}`} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                    <td className="py-1.5 px-2 text-slate-400 font-mono">{new Date(h.timestamp_utc).toLocaleTimeString()}</td>
                    <td className="py-1.5 px-2 text-right text-white">{h.speedKmh} km/h</td>
                    <td className="py-1.5 px-2 text-right text-sky-400 font-mono">{h.advisoryStoppingDist_m.toFixed(0)}m</td>
                    <td className="py-1.5 px-2 text-right text-amber-400 font-mono">{h.certifiedStoppingDist_m.toFixed(0)}m</td>
                    <td className="py-1.5 px-2 text-right text-white font-mono">{h.adhesionCoeff}</td>
                    <td className="py-1.5 px-2 text-right text-white font-mono">{(h.brakingPhases.brakeFade * 100).toFixed(0)}%</td>
                    <td className="py-1.5 px-2 text-center">{h.safetyInvariant.satisfied ? '\u2705' : '\u274C'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
