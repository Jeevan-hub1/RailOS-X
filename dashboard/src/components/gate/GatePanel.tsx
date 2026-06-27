'use client'

import { useState, useEffect } from 'react'
import { getGateQueue, enqueueAdvisory, authorizeAdvisory, type QueuedAdvisory } from '@/lib/api'
import { tierColor, tierLabel } from '@/lib/utils'

export function GatePanel() {
  const [queue, setQueue] = useState<QueuedAdvisory[]>([])
  const [actionLog, setActionLog] = useState<{ time: string; action: string; id: string }[]>([])
  const [loading, setLoading] = useState(false)

  const refreshQueue = async () => {
    try {
      const data = await getGateQueue()
      setQueue(data.advisories)
    } catch (e) { console.error(e) }
  }

  useEffect(() => { refreshQueue() }, [])

  const simulateAdvisory = async () => {
    const id = `adv-${Date.now().toString(36)}`
    const severities = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
    const types = ['TRACK_DEFECT', 'BRAKE_ADVISORY', 'SIGNAL_ANOMALY', 'OBSTRUCTION']
    const sev = severities[Math.floor(Math.random() * severities.length)]
    const type = types[Math.floor(Math.random() * types.length)]
    const prob = +(Math.random() * 0.5 + 0.5).toFixed(2)

    await enqueueAdvisory(id, { type, source: 'simulation' }, prob, sev)
    refreshQueue()
  }

  const handleAction = async (advisoryId: string, action: 'AUTHORIZE' | 'REJECT') => {
    setLoading(true)
    const res = await authorizeAdvisory(advisoryId, 'OC-Sharma-001', action)
    setActionLog(prev => [{
      time: new Date().toLocaleTimeString(),
      action: `${action} → ${res.status}`,
      id: advisoryId,
    }, ...prev].slice(0, 20))
    refreshQueue()
    setLoading(false)
  }

  return (
    <div className="space-y-6">
      {/* Gate Status */}
      <div className="grid grid-cols-3 gap-4">
        <div className="glass-panel p-4">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">Queue Depth</p>
          <p className="text-3xl font-bold text-white mt-1">{queue.length}</p>
        </div>
        <div className="glass-panel p-4">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">Tier 1 (Dual-Auth)</p>
          <p className="text-3xl font-bold text-red-400 mt-1">{queue.filter(a => a.riskTier === 1).length}</p>
        </div>
        <div className="glass-panel p-4">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">Actions Today</p>
          <p className="text-3xl font-bold text-emerald-400 mt-1">{actionLog.length}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Advisory Queue */}
        <div className="lg:col-span-2 glass-panel p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-white">Advisory Queue</h3>
            <div className="flex gap-2">
              <button
                onClick={simulateAdvisory}
                className="px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-xs text-slate-300 hover:border-slate-500 transition-all"
              >
                + Simulate Advisory
              </button>
              <button
                onClick={refreshQueue}
                className="px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-xs text-slate-300 hover:border-slate-500 transition-all"
              >
                Refresh
              </button>
            </div>
          </div>

          {queue.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-40 text-slate-600">
              <span className="text-3xl mb-2">&#128274;</span>
              <p className="text-sm">Queue empty — all advisories processed</p>
            </div>
          ) : (
            <div className="space-y-3">
              {queue.map(adv => (
                <div key={adv.advisoryId} className={`p-4 rounded-lg border ${tierColor(adv.riskTier)}`}>
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold border ${tierColor(adv.riskTier)}`}>
                          TIER {adv.riskTier} — {tierLabel(adv.riskTier)}
                        </span>
                        {adv.riskTier === 1 && (
                          <span className="text-[10px] px-2 py-0.5 rounded bg-red-500/20 text-red-300">
                            DUAL-AUTH REQUIRED
                          </span>
                        )}
                      </div>
                      <p className="text-xs font-mono text-slate-300 mt-1">{adv.advisoryId}</p>
                      <p className="text-[10px] text-slate-500 mt-0.5">
                        Score: {adv.riskScore.toFixed(2)} | Type: {adv.payload?.type || 'UNKNOWN'}
                      </p>
                    </div>
                    <div className="flex gap-2 ml-4">
                      <button
                        onClick={() => handleAction(adv.advisoryId, 'AUTHORIZE')}
                        disabled={loading}
                        className="px-3 py-1.5 rounded-lg bg-emerald-600/20 border border-emerald-500/30 text-emerald-400 text-xs font-semibold hover:bg-emerald-600/30 disabled:opacity-50"
                      >
                        Authorize
                      </button>
                      <button
                        onClick={() => handleAction(adv.advisoryId, 'REJECT')}
                        disabled={loading}
                        className="px-3 py-1.5 rounded-lg bg-red-600/20 border border-red-500/30 text-red-400 text-xs font-semibold hover:bg-red-600/30 disabled:opacity-50"
                      >
                        Reject
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Action Log */}
        <div className="glass-panel p-5">
          <h3 className="text-sm font-semibold text-white mb-3">Audit Trail</h3>
          {actionLog.length === 0 ? (
            <p className="text-xs text-slate-600">No actions yet</p>
          ) : (
            <div className="space-y-2 max-h-[400px] overflow-y-auto">
              {actionLog.map((log, i) => (
                <div key={i} className="p-2.5 bg-slate-800/30 rounded-lg text-xs border border-slate-800">
                  <div className="flex items-center justify-between">
                    <span className="text-slate-500 font-mono">{log.time}</span>
                    <span className={log.action.includes('AUTHORIZE') ? 'text-emerald-400' : 'text-red-400'}>
                      {log.action.split(' ')[0]}
                    </span>
                  </div>
                  <p className="text-slate-400 mt-0.5 font-mono truncate">{log.id}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
