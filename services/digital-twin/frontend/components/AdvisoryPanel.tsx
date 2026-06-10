/**
 * Advisory Panel — max 5 visible, severity-descending, scrollable overflow (Req 34 C3)
 * Authorize/Reject controls min 44×44px (Req 12 C2, Req 34 C4)
 * DRIFT_WARNING indicator (Req 22 task 22.6)
 * Satisfies: Req 12, Req 29, Req 34
 */
import React, { useState } from 'react';
import type { Advisory } from '../pages/index';

interface Props {
  advisories:     Advisory[];
  severityColors: Record<string, string>;
}

const MAX_VISIBLE = 5;

export default function AdvisoryPanel({ advisories, severityColors }: Props) {
  const [authorized, setAuthorized]   = useState<Set<string>>(new Set());
  const [rejected,   setRejected]     = useState<Set<string>>(new Set());
  const [scrollOffset, setScrollOffset] = useState(0);

  const pending   = advisories.filter(a => !authorized.has(a.alertId) && !rejected.has(a.alertId));
  const visible   = pending.slice(scrollOffset, scrollOffset + MAX_VISIBLE);
  const remaining = Math.max(0, pending.length - MAX_VISIBLE);

  const handleAuthorize = (id: string) => setAuthorized(prev => new Set(prev).add(id));
  const handleReject    = (id: string) => setRejected(prev => new Set(prev).add(id));

  return (
    <div className="flex-1 overflow-hidden flex flex-col p-3 bg-gray-900">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-semibold text-gray-200 uppercase tracking-wide">
          Advisory Queue
        </span>
        {remaining > 0 && (
          <span className="bg-amber-600 text-white text-xs px-2 py-0.5 rounded-full font-bold">
            +{remaining} more
          </span>
        )}
      </div>

      <div className="space-y-2 overflow-y-auto flex-1">
        {visible.map(adv => {
          const severity = adv.severity ?? 'LOW';
          const colorClass = severityColors[severity] ?? 'bg-gray-700 text-white';
          const event = adv.event as Record<string, unknown>;
          const hasDriftWarning = Boolean(event.driftWarning);

          return (
            <div key={adv.alertId}
                 className="rounded border border-gray-600 bg-gray-800 p-2 text-xs">
              <div className="flex items-center gap-2 mb-1">
                <span className={`px-2 py-0.5 rounded font-bold ${colorClass}`}>
                  {severity}
                </span>
                <span className="text-gray-300 font-mono truncate flex-1">
                  {String(event.alertType ?? adv.category)}
                </span>
                {hasDriftWarning && (
                  <span className="bg-orange-600 text-white px-1 py-0.5 rounded text-xs font-bold"
                        title="Model drift warning — review carefully">
                    DRIFT
                  </span>
                )}
              </div>
              <div className="text-gray-400 mb-2 truncate">
                {String(event.assetId ?? event.trainId ?? adv.alertId)}
              </div>
              {/* Action buttons — min 44×44px (Req 12 C2, Req 34 C4) */}
              <div className="flex gap-2">
                <button
                  onClick={() => handleAuthorize(adv.alertId)}
                  className="flex-1 min-h-[44px] bg-green-700 hover:bg-green-600
                             text-white font-bold rounded border-2 border-green-500
                             flex items-center justify-center text-sm"
                  aria-label={`Authorize advisory ${adv.alertId}`}
                >
                  Authorize
                </button>
                <button
                  onClick={() => handleReject(adv.alertId)}
                  className="flex-1 min-h-[44px] bg-red-800 hover:bg-red-700
                             text-white font-bold rounded border-2 border-red-500
                             flex items-center justify-center text-sm"
                  aria-label={`Reject advisory ${adv.alertId}`}
                >
                  Reject
                </button>
              </div>
            </div>
          );
        })}

        {pending.length === 0 && (
          <div className="text-gray-500 text-sm text-center py-4">
            No pending advisories
          </div>
        )}
      </div>

      {/* Scroll navigation when > 5 advisories */}
      {pending.length > MAX_VISIBLE && (
        <div className="flex justify-between mt-2 pt-2 border-t border-gray-700">
          <button
            onClick={() => setScrollOffset(Math.max(0, scrollOffset - MAX_VISIBLE))}
            disabled={scrollOffset === 0}
            className="text-xs text-gray-400 hover:text-white disabled:opacity-30"
          >← Prev</button>
          <span className="text-xs text-gray-500">
            {scrollOffset + 1}–{Math.min(scrollOffset + MAX_VISIBLE, pending.length)} of {pending.length}
          </span>
          <button
            onClick={() => setScrollOffset(Math.min(scrollOffset + MAX_VISIBLE, pending.length - 1))}
            disabled={scrollOffset + MAX_VISIBLE >= pending.length}
            className="text-xs text-gray-400 hover:text-white disabled:opacity-30"
          >Next →</button>
        </div>
      )}
    </div>
  );
}
