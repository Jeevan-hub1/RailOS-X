'use client'

import { useState } from 'react'
import { getKavachAdvisory, type KavachAdvisory } from '@/lib/api'

export function KavachPanel() {
  const [speed, setSpeed] = useState(120)
  const [vibration, setVibration] = useState(1.5)
  const [result, setResult] = useState<KavachAdvisory | null>(null)
  const [loading, setLoading] = useState(false)
  const [history, setHistory] = useState<KavachAdvisory[]>([])

  const computeAdvisory = async () => {
    setLoading(true)
    try {
      const data = await getKavachAdvisory(speed, 28.6139, 77.2090, vibration)
      if ('alertType' in data) {
        setResult(data as KavachAdvisory)
        setHistory(prev => [data as KavachAdvisory, ...prev].slice(0, 10))
      }
    } catch (e) {
      console.error('Kavach API error:', e)
    }
    setLoading(false)
  }

  const safetyMargin = result
    ? ((result.advisoryStoppingDist_m - result.certifiedStoppingDist_m) / result.certifiedStoppingDist_m * 100).toFixed(1)
    : '0'

  return (
    <div className="space-y-6">
      {/* Safety Banner */}
      <div className="glass-panel p-4 border-amber-500/30 bg-amber-500/5">
        <div className="flex items-center gap-3">
          <span className="text-2xl">&#9888;&#65039;</span>
          <div>
            <p className="text-sm font-semibold text-amber-300">ADVISORY ONLY — NOT CERTIFIED</p>
            <p className="text-xs text-slate-400">Read-only overlay on Kavach 4.0. Never modifies certified safety logic. Hardware data diode enforced.</p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Input Controls */}
        <div className="glass-panel p-6">
          <h3 className="text-sm font-semibold text-white mb-5">Braking Curve Computation</h3>
          
          {/* Speed Slider */}
          <div className="mb-6">
            <div className="flex justify-between text-xs mb-2">
              <span className="text-slate-400">Train Speed</span>
              <span className="text-sky-400 font-mono font-bold">{speed} km/h</span>
            </div>
            <input
              type="range"
              min={0} max={200} step={5}
              value={speed}
              onChange={(e) => setSpeed(Number(e.target.value))}
              className="w-full h-2 rounded-full appearance-none cursor-pointer bg-slate-700 accent-sky-500"
            />
            <div className="flex justify-between text-[10px] text-slate-600 mt-1">
              <span>0</span><span>50</span><span>100</span><span>150</span><span>200</span>
            </div>
          </div>

          {/* Vibration Slider */}
          <div className="mb-6">
            <div className="flex justify-between text-xs mb-2">
              <span className="text-slate-400">Bogie Vibration (RMS)</span>
              <span className="text-purple-400 font-mono font-bold">{vibration.toFixed(1)} g</span>
            </div>
            <input
              type="range"
              min={0} max={5} step={0.1}
              value={vibration}
              onChange={(e) => setVibration(Number(e.target.value))}
              className="w-full h-2 rounded-full appearance-none cursor-pointer bg-slate-700 accent-purple-500"
            />
            <div className="flex justify-between text-[10px] text-slate-600 mt-1">
              <span>0 (dry)</span><span>2.5</span><span>5.0 (wet/rough)</span>
            </div>
          </div>

          {/* Fixed Parameters */}
          <div className="grid grid-cols-2 gap-3 mb-6 p-3 bg-slate-800/50 rounded-lg">
            <div className="text-xs">
              <span className="text-slate-500">Latitude</span>
              <p className="text-white font-mono">28.6139</p>
            </div>
            <div className="text-xs">
              <span className="text-slate-500">Longitude</span>
              <p className="text-white font-mono">77.2090</p>
            </div>
          </div>

          {/* Compute Button */}
          <button
            onClick={computeAdvisory}
            disabled={loading}
            className="w-full py-3 rounded-lg bg-gradient-to-r from-sky-600 to-blue-700 text-white font-semibold text-sm hover:from-sky-500 hover:to-blue-600 disabled:opacity-50 transition-all shadow-lg shadow-sky-500/20"
          >
            {loading ? 'Computing...' : 'Compute Braking Advisory'}
          </button>
        </div>

        {/* Results */}
        <div className="glass-panel p-6">
          <h3 className="text-sm font-semibold text-white mb-5">Physics Results</h3>
          
          {result ? (
            <div className="space-y-4">
              {/* Stopping Distance Comparison */}
              <div className="p-4 bg-slate-800/50 rounded-lg">
                <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-3">Stopping Distance</p>
                
                {/* Advisory Bar */}
                <div className="mb-3">
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-sky-400">Advisory (ML-enhanced)</span>
                    <span className="text-white font-mono">{result.advisoryStoppingDist_m} m</span>
                  </div>
                  <div className="h-4 bg-slate-700 rounded-full overflow-hidden">
                    <div className="h-full bg-gradient-to-r from-sky-500 to-sky-400 rounded-full transition-all"
                      style={{ width: `${Math.min(100, (result.advisoryStoppingDist_m / 1000) * 100)}%` }} />
                  </div>
                </div>

                {/* Certified Bar */}
                <div>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-amber-400">Certified (Kavach 4.0)</span>
                    <span className="text-white font-mono">{result.certifiedStoppingDist_m} m</span>
                  </div>
                  <div className="h-4 bg-slate-700 rounded-full overflow-hidden">
                    <div className="h-full bg-gradient-to-r from-amber-500 to-amber-400 rounded-full transition-all"
                      style={{ width: `${Math.min(100, (result.certifiedStoppingDist_m / 1000) * 100)}%` }} />
                  </div>
                </div>
              </div>

              {/* Safety Invariant */}
              <div className={`p-3 rounded-lg border ${
                result.advisoryStoppingDist_m >= result.certifiedStoppingDist_m
                  ? 'border-emerald-500/30 bg-emerald-500/5'
                  : 'border-red-500/30 bg-red-500/5'
              }`}>
                <div className="flex items-center gap-2">
                  <span className="text-lg">{result.advisoryStoppingDist_m >= result.certifiedStoppingDist_m ? '✅' : '❌'}</span>
                  <div>
                    <p className="text-xs font-semibold text-white">Safety Invariant: advisory &ge; certified</p>
                    <p className="text-[10px] text-slate-400">Margin: +{safetyMargin}% (Req 10 C3)</p>
                  </div>
                </div>
              </div>

              {/* Parameters */}
              <div className="grid grid-cols-2 gap-3">
                <ParamBox label="Adhesion (mu)" value={result.adhesionCoeff.toFixed(3)} />
                <ParamBox label="Gradient" value={`${result.gradientRad.toFixed(4)} rad`} />
                <ParamBox label="Speed" value={`${result.speedKmh} km/h`} />
                <ParamBox label="Alert ID" value={result.alertId.slice(0, 8)} mono />
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-48 text-slate-600">
              <span className="text-4xl mb-3">🛤️</span>
              <p className="text-sm">Adjust parameters and compute</p>
              <p className="text-xs mt-1">Physics braking model: v&sup2; / (2&mu;g&middot;cos&theta; + 2g&middot;sin&theta;)</p>
            </div>
          )}
        </div>
      </div>

      {/* History */}
      {history.length > 0 && (
        <div className="glass-panel p-5">
          <h3 className="text-sm font-semibold text-white mb-3">Advisory History</h3>
          <div className="space-y-2 max-h-48 overflow-y-auto">
            {history.map((h, i) => (
              <div key={i} className="flex items-center justify-between p-2 bg-slate-800/30 rounded-lg text-xs">
                <span className="text-slate-400 font-mono">{new Date(h.timestamp_utc).toLocaleTimeString()}</span>
                <span className="text-white">{h.speedKmh} km/h</span>
                <span className="text-sky-400">{h.advisoryStoppingDist_m} m</span>
                <span className="text-slate-500">&mu;={h.adhesionCoeff}</span>
                <span className="text-emerald-400">✓</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function ParamBox({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="p-3 bg-slate-800/50 rounded-lg">
      <p className="text-[10px] text-slate-500 uppercase">{label}</p>
      <p className={`text-sm text-white mt-0.5 ${mono ? 'font-mono' : ''}`}>{value}</p>
    </div>
  )
}
