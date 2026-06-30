'use client'

import { useState, useCallback, memo } from 'react'
import { submitDisruption, type MARLProposal, type MARLAssignment } from '@/lib/api'

const SAMPLE_TRAINS = [
  'Rajdhani-12301', 'Shatabdi-12002', 'Duronto-12213',
  'Garib-Rath-12909', 'Jan-Shatabdi-12055', 'Vande-Bharat-22436',
] as const

const DISRUPTION_TYPES = [
  { value: 'delayed_service', label: 'Delayed Service', icon: '\u23F1' },
  { value: 'cancelled_service', label: 'Cancelled Service', icon: '\u274C' },
  { value: 'blocked_segment', label: 'Blocked Segment', icon: '\u26D4' },
] as const

const PRIORITY_COLORS: Record<number, string> = {
  1: 'text-red-400', 2: 'text-amber-400', 3: 'text-sky-400',
  4: 'text-slate-300', 5: 'text-slate-400', 6: 'text-slate-500',
}

// ── Memoized sub-components ──────────────────────────────────────────────────
const MetricCard = memo(function MetricCard({ label, value, unit, color }:
  { label: string; value: string | number; unit?: string; color?: string }) {
  return (
    <div className="p-2.5 bg-slate-800/50 rounded-lg text-center">
      <p className="text-[9px] uppercase tracking-wider text-slate-500">{label}</p>
      <p className={`text-lg font-bold mt-0.5 ${color || 'text-white'}`}>
        {value}<span className="text-[10px] text-slate-500 ml-0.5">{unit}</span>
      </p>
    </div>
  )
})

const TimelineRow = memo(function TimelineRow({ a, idx }: { a: MARLAssignment; idx: number }) {
  const prioColor = PRIORITY_COLORS[a.priority] || 'text-slate-400'
  return (
    <div className="flex items-center gap-2 p-2.5 bg-slate-800/30 rounded-lg border border-slate-700/50">
      <div className="w-7 h-7 rounded bg-indigo-600/20 flex items-center justify-center text-indigo-400 text-[10px] font-bold">
        P{a.priority}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <p className={`text-xs font-semibold truncate ${prioColor}`}>{a.trainId}</p>
          <span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-400">{a.trainClass}</span>
        </div>
        <div className="flex items-center gap-2 mt-0.5">
          {a.actions.slice(0, 3).map((act, i) => (
            <span key={i} className="text-[9px] text-slate-500">
              {act.segmentId.slice(-7)} ({act.enterAt.slice(0,5)}-{act.exitAt.slice(0,5)})
              {act.platform != null && <span className="text-teal-400 ml-0.5">P{act.platform}</span>}
            </span>
          ))}
          {a.actions.length > 3 && <span className="text-[9px] text-slate-600">+{a.actions.length - 3}</span>}
        </div>
      </div>
      <div className="text-right">
        <p className={`text-xs font-mono ${a.delayDeltaMin > 10 ? 'text-red-400' : a.delayDeltaMin > 5 ? 'text-amber-400' : 'text-emerald-400'}`}>
          {a.delayDeltaMin > 0 ? '+' : ''}{a.delayDeltaMin} min
        </p>
        <p className="text-[9px] text-slate-500">{a.originalSlot || '—'} &rarr; {a.rescheduledSlot?.slice(0,5) || '—'}</p>
      </div>
    </div>
  )
})

// ── Main component ───────────────────────────────────────────────────────────
export function MARLPanel() {
  const [selectedTrains, setSelectedTrains] = useState<string[]>(['Rajdhani-12301', 'Shatabdi-12002'])
  const [disruptionType, setDisruptionType] = useState('delayed_service')
  const [proposal, setProposal] = useState<MARLProposal | null>(null)
  const [loading, setLoading] = useState(false)
  const [proposals, setProposals] = useState<MARLProposal[]>([])

  const generate = useCallback(async () => {
    setLoading(true)
    try {
      const id = `disruption-${Date.now()}`
      const data = await submitDisruption(id, disruptionType, selectedTrains)
      setProposal(data)
      setProposals(prev => [data, ...prev].slice(0, 5))
    } catch (e) { console.error(e) }
    setLoading(false)
  }, [disruptionType, selectedTrains])

  const toggleTrain = useCallback((t: string) => {
    setSelectedTrains(prev => prev.includes(t) ? prev.filter(x => x !== t) : [...prev, t])
  }, [])

  const m = proposal?.metrics

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* ── Input Panel ─────────────────────────────────────────────────── */}
        <div className="glass-panel p-5">
          <h3 className="text-sm font-semibold text-white mb-4">Disruption Event</h3>

          {/* Type selector */}
          <div className="mb-4">
            <label className="text-[10px] text-slate-400 mb-1.5 block uppercase">Type</label>
            <div className="grid grid-cols-3 gap-2">
              {DISRUPTION_TYPES.map(dt => (
                <button key={dt.value} onClick={() => setDisruptionType(dt.value)}
                  className={`p-2 rounded-lg text-center border transition-all text-[10px] ${
                    disruptionType === dt.value
                      ? 'bg-indigo-600/20 border-indigo-500/50 text-indigo-300'
                      : 'bg-slate-800/50 border-slate-700 text-slate-400 hover:border-slate-600'}`}>
                  <span className="text-lg block">{dt.icon}</span>
                  {dt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Train selector */}
          <div className="mb-4">
            <label className="text-[10px] text-slate-400 mb-1.5 block uppercase">Affected Trains</label>
            <div className="grid grid-cols-2 gap-1.5">
              {SAMPLE_TRAINS.map(t => (
                <button key={t} onClick={() => toggleTrain(t)}
                  className={`px-2 py-1.5 rounded text-[10px] font-medium border transition-all ${
                    selectedTrains.includes(t)
                      ? 'bg-sky-600/20 border-sky-500/50 text-sky-300'
                      : 'bg-slate-800/50 border-slate-700 text-slate-400 hover:border-slate-600'}`}>
                  {t}
                </button>
              ))}
            </div>
          </div>

          <button onClick={generate} disabled={loading || selectedTrains.length === 0}
            className="w-full py-3 rounded-lg bg-gradient-to-r from-indigo-600 to-purple-700 text-white font-semibold text-sm hover:from-indigo-500 hover:to-purple-600 disabled:opacity-50 transition-all">
            {loading ? 'Computing (PPO)...' : 'Generate Proposal'}
          </button>

          {/* Constraints info */}
          {proposal && proposal.constraints && (
            <div className="mt-3 p-2.5 bg-slate-800/30 rounded-lg text-[10px] text-slate-500">
              <p>Corridor: NDLS-MERT ({proposal.constraints.corridorLength_km}km)</p>
              <p>Segments: {proposal.constraints.segmentsEvaluated} | Headway: {proposal.constraints.minHeadwaySeconds}s</p>
              <p>Model: v{proposal.modelVersion} | Compute: {proposal.metrics?.computationMs ?? '—'}ms</p>
            </div>
          )}
        </div>

        {/* ── Metrics Panel ───────────────────────────────────────────────── */}
        <div className="glass-panel p-5">
          <h3 className="text-sm font-semibold text-white mb-4">Optimization Metrics</h3>

          {m ? (
            <div className="space-y-4">
              {/* Conflict status */}
              <div className={`p-3 rounded-lg border ${
                proposal!.conflictFree ? 'border-emerald-500/30 bg-emerald-500/5' : 'border-red-500/30 bg-red-500/5'}`}>
                <div className="flex items-center gap-2">
                  <span className="text-lg">{proposal!.conflictFree ? '\u2705' : '\u274C'}</span>
                  <div>
                    <p className="text-xs font-semibold text-white">{proposal!.conflictFree ? 'CONFLICT-FREE' : 'CONFLICTS REMAIN'}</p>
                    <p className="text-[10px] text-slate-400">Risk: Tier {proposal!.riskTier} (score {proposal!.riskScore})</p>
                  </div>
                </div>
              </div>

              {/* Metrics grid */}
              <div className="grid grid-cols-2 gap-2">
                <MetricCard label="Total Delay" value={m.totalDelayMin ?? 0} unit="min" color="text-amber-400" />
                <MetricCard label="Max Single" value={m.maxSingleDelayMin ?? 0} unit="min" color="text-red-400" />
                <MetricCard label="Passengers" value={m.affectedPassengers ?? 0} color="text-sky-400" />
                <MetricCard label="Energy" value={`+${m.energyImpactPct ?? 0}`} unit="%" color="text-orange-400" />
                <MetricCard label="Conflicts Fixed" value={m.conflictsResolved ?? 0} color="text-emerald-400" />
                <MetricCard label="Platforms" value={m.platformReassignments ?? 0} color="text-teal-400" />
              </div>

              {/* Delay distribution bar */}
              <div>
                <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5">Delay Distribution</p>
                <div className="space-y-1">
                  {(proposal?.assignments || []).map((a, i) => {
                    const maxD = Math.max(...(proposal?.assignments || []).map(x => Math.abs(x.delayDeltaMin || 0)), 1)
                    const pct = (Math.abs(a.delayDeltaMin || 0) / maxD) * 100
                    return (
                      <div key={i} className="flex items-center gap-2">
                        <span className="text-[9px] text-slate-400 w-20 truncate">{a.trainId?.slice(-10) || '—'}</span>
                        <div className="flex-1 h-2 bg-slate-700 rounded-full overflow-hidden">
                          <div className={`h-full rounded-full ${(a.delayDeltaMin || 0) > 10 ? 'bg-red-500' : (a.delayDeltaMin || 0) > 5 ? 'bg-amber-500' : 'bg-emerald-500'}`}
                            style={{ width: `${pct}%` }} />
                        </div>
                        <span className="text-[9px] font-mono text-white w-8 text-right">{a.delayDeltaMin || 0}m</span>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-52 text-slate-600">
              <span className="text-3xl mb-2">&#128202;</span>
              <p className="text-sm">Metrics appear after generation</p>
            </div>
          )}
        </div>

        {/* ── Timeline Panel ──────────────────────────────────────────────── */}
        <div className="glass-panel p-5">
          <h3 className="text-sm font-semibold text-white mb-4">Rescheduled Timeline</h3>

          {proposal ? (
            <div className="space-y-2 max-h-[420px] overflow-y-auto">
              {proposal.assignments.map((a, i) => <TimelineRow key={`${a.trainId}-${i}`} a={a} idx={i} />)}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-52 text-slate-600">
              <span className="text-3xl mb-2">&#128646;</span>
              <p className="text-sm">Select trains and generate</p>
              <p className="text-[10px] mt-1">Priority-based conflict resolution</p>
            </div>
          )}
        </div>
      </div>

      {/* ── Proposal History ──────────────────────────────────────────────── */}
      {proposals.length > 0 && (
        <div className="glass-panel p-4">
          <h3 className="text-sm font-semibold text-white mb-3">Recent Proposals</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-slate-500 border-b border-slate-800">
                  <th className="text-left py-1.5 px-2">ID</th>
                  <th className="text-left py-1.5 px-2">Type</th>
                  <th className="text-right py-1.5 px-2">Trains</th>
                  <th className="text-right py-1.5 px-2">Delay</th>
                  <th className="text-right py-1.5 px-2">Conflicts</th>
                  <th className="text-right py-1.5 px-2">Pax</th>
                  <th className="text-center py-1.5 px-2">Status</th>
                  <th className="text-right py-1.5 px-2">Time</th>
                </tr>
              </thead>
              <tbody>
                {proposals.map((p, i) => (
                  <tr key={p.proposalId} className="border-b border-slate-800/50 hover:bg-slate-800/30 cursor-pointer"
                    onClick={() => setProposal(p)}>
                    <td className="py-1.5 px-2 font-mono text-slate-400">{p.proposalId.slice(0, 8)}</td>
                    <td className="py-1.5 px-2 text-white">{p.disruptionType?.replace(/_/g, ' ') ?? '—'}</td>
                    <td className="py-1.5 px-2 text-right text-white">{p.assignments.length}</td>
                    <td className="py-1.5 px-2 text-right text-amber-400">{p.metrics?.totalDelayMin ?? '—'}m</td>
                    <td className="py-1.5 px-2 text-right text-emerald-400">{p.metrics?.conflictsResolved ?? '—'}</td>
                    <td className="py-1.5 px-2 text-right text-sky-400">{p.metrics?.affectedPassengers ?? '—'}</td>
                    <td className="py-1.5 px-2 text-center">
                      <span className={`text-[9px] px-1.5 py-0.5 rounded ${p.conflictFree ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'}`}>
                        {p.conflictFree ? 'OK' : 'CONFLICT'}
                      </span>
                    </td>
                    <td className="py-1.5 px-2 text-right text-slate-500 font-mono">{p.metrics?.computationMs ?? '—'}ms</td>
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
