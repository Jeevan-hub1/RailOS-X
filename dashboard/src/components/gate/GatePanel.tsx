'use client'

import { useState, useEffect, useCallback, useRef, memo } from 'react'
import {
  getGateQueue, enqueueAdvisory, authorizeAdvisory, getGateStats, getGateControllers,
  type QueuedAdvisory, type GateStats, type GateController,
} from '@/lib/api'
import { tierBorderBg, tierLabel, tierBadge, formatDuration } from '@/lib/utils'

function tierColor(tier: number): string {
  return tierBorderBg(tier)
}
function formatAge(seconds: number): string {
  return formatDuration(seconds)
}

// ── Sub-components ───────────────────────────────────────────────────────────
const StatCard = memo(function StatCard({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <div className="glass-panel p-3">
      <p className="text-[9px] uppercase tracking-wider text-slate-500">{label}</p>
      <p className={`text-2xl font-bold mt-0.5 ${color || 'text-white'}`}>{value}</p>
    </div>
  )
})

const EscalationBar = memo(function EscalationBar({ ageS, timeoutS, escalated }: { ageS: number; timeoutS: number; escalated: boolean }) {
  const pct = Math.min(100, (ageS / timeoutS) * 100)
  const barColor = escalated ? 'bg-red-500 animate-pulse' : pct > 75 ? 'bg-amber-500' : 'bg-emerald-500'
  return (
    <div className="flex items-center gap-1.5">
      <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${barColor}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[9px] font-mono text-slate-400 w-10 text-right">
        {escalated ? 'ESC' : formatAge(Math.max(0, timeoutS - ageS))}
      </span>
    </div>
  )
})

const AdvisoryCard = memo(function AdvisoryCard({ adv, controllers, onAction, loading }: {
  adv: QueuedAdvisory; controllers: GateController[]; onAction: (id: string, action: 'AUTHORIZE' | 'REJECT', cid: string) => void; loading: boolean
}) {
  const [selectedController, setSelectedController] = useState(controllers?.[0]?.id || 'OC-Sharma-001')
  return (
    <div className={`p-3.5 rounded-lg border ${tierColor(adv.riskTier)} ${adv.escalated ? 'ring-1 ring-red-500/40' : ''}`}>
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <span className={`text-[9px] px-2 py-0.5 rounded-full font-bold border ${tierColor(adv.riskTier)}`}>
              TIER {adv.riskTier} — {tierLabel(adv.riskTier)}
            </span>
            <span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-400">{adv.severity}</span>
            {adv.escalated && <span className="text-[9px] px-1.5 py-0.5 rounded bg-red-500/20 text-red-300 animate-pulse">ESCALATED x{adv.escalationCount}</span>}
            {adv.awaitingSecondAuth && <span className="text-[9px] px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300">DUAL-AUTH</span>}
          </div>
          <p className="text-[11px] font-mono text-slate-300 truncate">{adv.advisoryId}</p>
          <div className="flex items-center gap-3 mt-1 text-[10px] text-slate-500">
            <span>Score: {adv.riskScore}</span>
            <span>Source: {adv.source}</span>
            <span>Age: {formatAge(adv.ageSeconds)}</span>
            <span>Type: {adv.payload?.type || '—'}</span>
          </div>
          {/* Escalation countdown */}
          <div className="mt-2">
            <EscalationBar ageS={adv.ageSeconds} timeoutS={adv.escalationTimeoutS} escalated={adv.escalated} />
          </div>
          {adv.awaitingSecondAuth && adv.firstAuthBy && (
            <p className="text-[10px] text-purple-400 mt-1.5">First auth by: {adv.firstAuthBy} at {adv.firstAuthAt?.slice(11, 19)}</p>
          )}
        </div>
        {/* Actions */}
        <div className="flex flex-col gap-1.5 items-end">
          <select value={selectedController} onChange={e => setSelectedController(e.target.value)}
            className="bg-slate-800 border border-slate-700 rounded text-[10px] text-white px-1.5 py-1 w-32">
            {(controllers || []).map(c => <option key={c.id} value={c.id}>{c.name} ({c.role?.slice(0,3)})</option>)}
          </select>
          <button onClick={() => onAction(adv.advisoryId, 'AUTHORIZE', selectedController)} disabled={loading}
            className="w-32 px-2 py-1.5 rounded bg-emerald-600/20 border border-emerald-500/30 text-emerald-400 text-[10px] font-semibold hover:bg-emerald-600/30 disabled:opacity-50">
            Authorize
          </button>
          <button onClick={() => onAction(adv.advisoryId, 'REJECT', selectedController)} disabled={loading}
            className="w-32 px-2 py-1.5 rounded bg-red-600/20 border border-red-500/30 text-red-400 text-[10px] font-semibold hover:bg-red-600/30 disabled:opacity-50">
            Reject
          </button>
        </div>
      </div>
    </div>
  )
})

const AuditRow = memo(function AuditRow({ log }: { log: { time: string; action: string; id: string; controller: string; decisionTime: number } }) {
  return (
    <div className="p-2 bg-slate-800/30 rounded text-[10px] border border-slate-800">
      <div className="flex items-center justify-between">
        <span className="text-slate-500 font-mono">{log.time}</span>
        <span className={log.action.includes('AUTH') ? 'text-emerald-400' : 'text-red-400'}>{log.action}</span>
      </div>
      <div className="flex items-center justify-between mt-0.5">
        <span className="text-slate-400 font-mono truncate max-w-[120px]">{log.id}</span>
        <span className="text-slate-500">{log.controller} ({log.decisionTime}s)</span>
      </div>
    </div>
  )
})

// ── Main component ───────────────────────────────────────────────────────────
export function GatePanel() {
  const [queue, setQueue] = useState<QueuedAdvisory[]>([])
  const [stats, setStats] = useState<GateStats | null>(null)
  const [controllers, setControllers] = useState<GateController[]>([])
  const [actionLog, setActionLog] = useState<{ time: string; action: string; id: string; controller: string; decisionTime: number }[]>([])
  const [loading, setLoading] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval>>()

  const refreshQueue = useCallback(async () => {
    try {
      const [qData, sData] = await Promise.all([getGateQueue(), getGateStats()])
      setQueue(qData.advisories)
      setStats(sData)
    } catch (e) { console.error(e) }
  }, [])

  // Initial load + polling
  useEffect(() => {
    refreshQueue()
    getGateControllers().then(d => setControllers(d.controllers)).catch(() => {})
    pollRef.current = setInterval(refreshQueue, 3000)
    return () => clearInterval(pollRef.current)
  }, [refreshQueue])

  const simulateAdvisory = useCallback(async () => {
    const id = `adv-${Date.now().toString(36)}`
    const severities = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] as const
    const types = ['TRACK_DEFECT', 'BRAKE_ADVISORY', 'SIGNAL_ANOMALY', 'OBSTRUCTION', 'THERMAL_ALERT'] as const
    const sources = ['kavach_advisory', 'marl_scheduler', 'vision_defect', 'edge_compute'] as const
    const sev = severities[Math.floor(Math.random() * severities.length)]
    const type = types[Math.floor(Math.random() * types.length)]
    const source = sources[Math.floor(Math.random() * sources.length)]
    const prob = +(Math.random() * 0.5 + 0.5).toFixed(2)
    await enqueueAdvisory(id, { type, source: 'simulation' }, prob, sev, source)
    refreshQueue()
  }, [refreshQueue])

  const handleAction = useCallback(async (advisoryId: string, action: 'AUTHORIZE' | 'REJECT', controllerId: string) => {
    setLoading(true)
    try {
      const res = await authorizeAdvisory(advisoryId, controllerId, action)
      const ctrl = controllers.find(c => c.id === controllerId)
      setActionLog(prev => [{
        time: new Date().toLocaleTimeString(),
        action: `${action} \u2192 ${res.status}`,
        id: advisoryId.slice(0, 12),
        controller: ctrl?.name || controllerId,
        decisionTime: res.decisionTimeS || 0,
      }, ...prev].slice(0, 30))
      refreshQueue()
    } catch (e) { console.error(e) }
    setLoading(false)
  }, [refreshQueue, controllers])

  const tier1Count = queue.filter(a => a.riskTier === 1).length
  const escalatedCount = queue.filter(a => a.escalated).length

  return (
    <div className="space-y-5">
      {/* Stats Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
        <StatCard label="Queue" value={queue.length} color="text-white" />
        <StatCard label="Tier 1" value={tier1Count} color="text-red-400" />
        <StatCard label="Escalated" value={escalatedCount} color="text-amber-400" />
        <StatCard label="Auth Rate" value={stats ? `${stats.authorizationRate}%` : '—'} color="text-emerald-400" />
        <StatCard label="Avg Decision" value={stats ? `${stats.avgDecisionTimeS}s` : '—'} color="text-sky-400" />
        <StatCard label="Total Processed" value={stats ? stats.totalAuthorized + stats.totalRejected : 0} color="text-purple-400" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-5">
        {/* Advisory Queue — 3 cols */}
        <div className="lg:col-span-3 glass-panel p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-white">Authorization Queue</h3>
            <div className="flex gap-2">
              <button onClick={simulateAdvisory}
                className="px-2.5 py-1 rounded bg-slate-800 border border-slate-700 text-[10px] text-slate-300 hover:border-slate-500">
                + Simulate
              </button>
              <button onClick={refreshQueue}
                className="px-2.5 py-1 rounded bg-slate-800 border border-slate-700 text-[10px] text-slate-300 hover:border-slate-500">
                Refresh
              </button>
            </div>
          </div>

          {queue.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-32 text-slate-600">
              <span className="text-2xl mb-1">&#128274;</span>
              <p className="text-xs">Queue empty — all advisories processed</p>
            </div>
          ) : (
            <div className="space-y-2.5 max-h-[480px] overflow-y-auto">
              {queue.map(adv => (
                <AdvisoryCard key={adv.advisoryId} adv={adv} controllers={controllers}
                  onAction={handleAction} loading={loading} />
              ))}
            </div>
          )}
        </div>

        {/* Audit Trail — 1 col */}
        <div className="glass-panel p-4">
          <h3 className="text-sm font-semibold text-white mb-3">Audit Trail</h3>
          {actionLog.length === 0 ? (
            <p className="text-[10px] text-slate-600">No actions yet</p>
          ) : (
            <div className="space-y-1.5 max-h-[480px] overflow-y-auto">
              {actionLog.map((log, i) => <AuditRow key={`${log.id}-${i}`} log={log} />)}
            </div>
          )}

          {/* Tier breakdown */}
          {stats && (
            <div className="mt-4 pt-3 border-t border-slate-800">
              <p className="text-[9px] uppercase tracking-wider text-slate-500 mb-2">Tier Breakdown</p>
              {[1, 2, 3].map(tier => {
                const count = (stats.tierBreakdown && stats.tierBreakdown[tier]) || 0
                const total = stats.totalEnqueued || 1
                return (
                  <div key={tier} className="flex items-center gap-2 mb-1">
                    <span className="text-[9px] text-slate-400 w-10">Tier {tier}</span>
                    <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                      <div className={`h-full rounded-full ${tier === 1 ? 'bg-red-500' : tier === 2 ? 'bg-amber-500' : 'bg-slate-500'}`}
                        style={{ width: `${(count / total) * 100}%` }} />
                    </div>
                    <span className="text-[9px] font-mono text-slate-400 w-6 text-right">{count}</span>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
