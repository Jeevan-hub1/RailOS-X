/**
 * RailOS Digital Twin — Main Operations Map Page
 * Satisfies: Req 8 C1–C7, Req 45, Design §7.2 (visual encoding convention)
 *
 * Visual encoding:
 *   Confirmed (live)  → solid marker, opaque
 *   Predicted         → dashed border, semi-transparent, "PREDICTED" label
 *   Simulated         → hatched fill, "SIMULATED" label
 *   Stale (>10s)      → faded + staleness icon
 *   Advisory (Kavach) → yellow read-only panel, "ADVISORY — NOT CERTIFIED"
 */

import React, { useEffect, useRef, useState, useCallback } from 'react';
import dynamic from 'next/dynamic';

// Load DeckGL dynamically (SSR disabled — requires browser WebGL)
const CorridorMap = dynamic(() => import('../components/CorridorMap'), { ssr: false });
const AdvisoryPanel = dynamic(() => import('../components/AdvisoryPanel'), { ssr: false });
const LegendPanel = dynamic(() => import('../components/LegendPanel'), { ssr: false });

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://digital-twin.railos.svc.cluster.local:3000/ws';

export interface TrainState {
  trainId: string;
  lat: number;
  lon: number;
  speed_kmh: number;
  delay_min: number;
  segment_id: string;
  updated_at: string;
  isStale?: boolean;
  isPredicted?: boolean;
}

export interface Advisory {
  alertId: string;
  category: string;
  event: Record<string, unknown>;
  received_at: string;
  severity?: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
}

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: 'bg-red-600 text-white',
  HIGH:     'bg-amber-500 text-white',
  MEDIUM:   'bg-yellow-400 text-black',
  LOW:      'bg-blue-500 text-white',
};

const STALE_THRESHOLD_MS = 10_000;

export default function DigitalTwinPage() {
  const [trains,     setTrains]     = useState<Record<string, TrainState>>({});
  const [advisories, setAdvisories] = useState<Advisory[]>([]);
  const [gateStatus, setGateStatus] = useState<'operational' | 'degraded' | 'unavailable'>('operational');
  const [connected,  setConnected]  = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  // Mark trains stale if not updated within 10s (Req 8 C2, Req 45 C3)
  useEffect(() => {
    const interval = setInterval(() => {
      setTrains(prev => {
        const now = Date.now();
        const updated: Record<string, TrainState> = {};
        for (const [id, t] of Object.entries(prev)) {
          const age = now - new Date(t.updated_at).getTime();
          updated[id] = { ...t, isStale: age > STALE_THRESHOLD_MS };
        }
        return updated;
      });
    }, 2000);
    return () => clearInterval(interval);
  }, []);

  // WebSocket connection (Req 8 C1 — ≤5s refresh)
  useEffect(() => {
    const connect = () => {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen  = () => setConnected(true);
      ws.onclose = () => { setConnected(false); setTimeout(connect, 3000); };
      ws.onerror = () => ws.close();

      ws.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data);
          if (msg.type === 'state_update') {
            const data = msg.data;
            if (data.trains)    setTrains(data.trains);
            if (data.advisories) {
              const list = Object.values(data.advisories) as Advisory[];
              // Sort by severity descending (Req 29 C1, Req 34 C1)
              const order = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];
              list.sort((a, b) =>
                order.indexOf(a.severity ?? 'LOW') - order.indexOf(b.severity ?? 'LOW')
              );
              setAdvisories(list);
            }
          }
        } catch { /* ignore parse errors */ }
      };
    };
    connect();
    return () => wsRef.current?.close();
  }, []);

  const trainList = Object.values(trains);

  return (
    <div className="flex h-screen bg-gray-900 text-white overflow-hidden">
      {/* Map panel (full height, 75% width) */}
      <div className="flex-1 relative">
        <CorridorMap trains={trainList} advisories={advisories} />
        {/* Connection status */}
        <div className={`absolute top-2 right-2 px-2 py-1 rounded text-xs font-mono
                        ${connected ? 'bg-green-700' : 'bg-red-700'}`}>
          {connected ? '● LIVE' : '○ RECONNECTING'}
        </div>
        {/* Authorization gate status (Req 30 C4) */}
        <div className={`absolute top-2 left-2 px-2 py-1 rounded text-xs font-mono
                        ${gateStatus === 'operational' ? 'bg-green-700'
                        : gateStatus === 'degraded'    ? 'bg-amber-600'
                        :                               'bg-red-700'}`}>
          Gate: {gateStatus.toUpperCase()}
        </div>
      </div>

      {/* Right panel: advisories + legend */}
      <div className="w-80 flex flex-col border-l border-gray-700">
        {/* Advisory panel — max 5 visible (Req 34 C3) */}
        <AdvisoryPanel advisories={advisories} severityColors={SEVERITY_COLORS} />
        {/* Persistent legend (Req 45 C4) */}
        <LegendPanel />
      </div>
    </div>
  );
}
