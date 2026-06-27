'use client'

import { useState } from 'react'
import { submitDisruption, type MARLProposal } from '@/lib/api'

const SAMPLE_TRAINS = [
  'Rajdhani-12301', 'Shatabdi-12002', 'Duronto-12213',
  'Garib-Rath-12909', 'Jan-Shatabdi-12055', 'Vande-Bharat-22436',
]

export function MARLPanel() {
  const [selectedTrains, setSelectedTrains] = useState<string[]>(['Rajdhani-12301', 'Shatabdi-12002'])
  const [disruptionType, setDisruptionType] = useState('delayed_service')
  const [proposal, setProposal] = useState<MARLProposal | null>(null)
  const [loading, setLoading] = useState(false)
  const [proposals, setProposals] = useState<MARLProposal[]>([])

  const generate = async () => {
    setLoading(true)
    try {
      const id = `disruption-${Date.now()}`
      const data = await submitDisruption(id, disruptionType, selectedTrains)
      setProposal(data)
      setProposals(prev => [data, ...prev].slice(0, 5))
    } catch (e) { console.error(e) }
    setLoading(false)
  }

  const toggleTrain = (t: string) => {
    setSelectedTrains(prev =>
      prev.includes(t) ? prev.filter(x => x !== t) : [...prev, t]
    )
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Disruption Input */}
        <div className="glass-panel p-6">
          <h3 className="text-sm font-semibold text-white mb-4">Simulate Disruption Event</h3>

          <div className="mb-4">
            <label className="text-xs text-slate-400 mb-2 block">Disruption Type</label>
            <select
              value={disruptionType}
              onChange={(e) => setDisruptionType(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white"
            >
              <option value="delayed_service">Delayed Service</option>
              <option value="cancelled_service">Cancelled Service</option>
              <option value="blocked_segment">Blocked Segment</option>
            </select>
          </div>

          <div className="mb-5">
            <label className="text-xs text-slate-400 mb-2 block">Affected Trains</label>
            <div className="grid grid-cols-2 gap-2">
              {SAMPLE_TRAINS.map(t => (
                <button
                  key={t}
                  onClick={() => toggleTrain(t)}
                  className={`px-3 py-2 rounded-lg text-xs font-medium transition-all border ${
                    selectedTrains.includes(t)
                      ? 'bg-sky-600/20 border-sky-500/50 text-sky-300'
                      : 'bg-slate-800/50 border-slate-700 text-slate-400 hover:border-slate-600'
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>

          <button
            onClick={generate}
            disabled={loading || selectedTrains.length === 0}
            className="w-full py-3 rounded-lg bg-gradient-to-r from-indigo-600 to-purple-700 text-white font-semibold text-sm hover:from-indigo-500 hover:to-purple-600 disabled:opacity-50 transition-all"
          >
            {loading ? 'Computing (PPO inference)...' : 'Generate Rescheduling Proposal'}
          </button>
          <p className="text-[10px] text-slate-600 mt-2 text-center">Timeout: 30s | Flatland-RL environment</p>
        </div>

        {/* Proposal Result */}
        <div className="glass-panel p-6">
          <h3 className="text-sm font-semibold text-white mb-4">Proposal Output</h3>

          {proposal ? (
            <div className="space-y-4">
              {/* Status Badge */}
              <div className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg ${
                proposal.conflictFree ? 'bg-emerald-500/10 border border-emerald-500/30' : 'bg-red-500/10 border border-red-500/30'
              }`}>
                <span>{proposal.conflictFree ? '✅' : '❌'}</span>
                <span className={`text-xs font-semibold ${proposal.conflictFree ? 'text-emerald-400' : 'text-red-400'}`}>
                  {proposal.conflictFree ? 'CONFLICT-FREE' : 'CONFLICT DETECTED'}
                </span>
              </div>

              {/* Metadata */}
              <div className="grid grid-cols-2 gap-3">
                <div className="p-2.5 bg-slate-800/50 rounded-lg">
                  <p className="text-[10px] text-slate-500">Model Version</p>
                  <p className="text-sm text-white font-mono">v{proposal.modelVersion}</p>
                </div>
                <div className="p-2.5 bg-slate-800/50 rounded-lg">
                  <p className="text-[10px] text-slate-500">Risk Tier</p>
                  <p className="text-sm text-white">{proposal.riskTier} (score: {proposal.riskScore})</p>
                </div>
              </div>

              {/* Timeline */}
              <div>
                <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Segment Assignments</p>
                <div className="space-y-2">
                  {proposal.assignments.map((a, i) => (
                    <div key={i} className="flex items-center gap-3 p-2.5 bg-slate-800/30 rounded-lg border border-slate-700/50">
                      <div className="w-8 h-8 rounded-lg bg-indigo-600/20 flex items-center justify-center text-indigo-400 text-xs font-bold">
                        {i + 1}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium text-white truncate">{a.trainId}</p>
                        <p className="text-[10px] text-slate-500">
                          {a.actions[0]?.segmentId} | {a.actions[0]?.enterAt} — {a.actions[0]?.exitAt}
                        </p>
                      </div>
                      <span className="text-[10px] text-emerald-400">{a.delayDeltaMin} min</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-48 text-slate-600">
              <span className="text-4xl mb-3">🚂</span>
              <p className="text-sm">No proposals generated yet</p>
              <p className="text-xs mt-1">Select trains and submit a disruption</p>
            </div>
          )}
        </div>
      </div>

      {/* Proposal History */}
      {proposals.length > 0 && (
        <div className="glass-panel p-5">
          <h3 className="text-sm font-semibold text-white mb-3">Recent Proposals</h3>
          <div className="space-y-2">
            {proposals.map((p, i) => (
              <div key={i} className="flex items-center justify-between p-3 bg-slate-800/30 rounded-lg text-xs">
                <span className="font-mono text-slate-400">{p.proposalId.slice(0, 12)}...</span>
                <span className="text-white">{p.assignments.length} trains</span>
                <span className={p.conflictFree ? 'text-emerald-400' : 'text-red-400'}>
                  {p.conflictFree ? 'Conflict-free' : 'Has conflicts'}
                </span>
                <span className="text-slate-500">v{p.modelVersion}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
