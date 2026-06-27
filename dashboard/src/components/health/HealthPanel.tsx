'use client'

import { useState, useEffect } from 'react'
import { getKavachHealth, getMARLHealth, getGateHealth } from '@/lib/api'

interface ServiceStatus {
  name: string
  url: string
  status: 'ok' | 'degraded' | 'down'
  latency?: number
  details?: string
}

export function HealthPanel() {
  const [services, setServices] = useState<ServiceStatus[]>([
    { name: 'Kavach++ Advisory', url: ':8082', status: 'down' },
    { name: 'MARL Scheduler', url: ':8081', status: 'down' },
    { name: 'Authorization Gate', url: ':8087', status: 'down' },
  ])
  const [infra, setInfra] = useState([
    { name: 'Apache Kafka', port: '9092', status: 'ok' as const, detail: 'KRaft mode, 17 topics' },
    { name: 'PostgreSQL 16', port: '5433', status: 'ok' as const, detail: 'Auth audit, hazard register' },
    { name: 'InfluxDB 2.7', port: '8086', status: 'ok' as const, detail: 'Time-series telemetry' },
    { name: 'Redis 7', port: '6380', status: 'ok' as const, detail: 'Cache & pub/sub' },
    { name: 'MinIO (S3)', port: '9000', status: 'ok' as const, detail: 'MLflow artifacts, WORM' },
  ])
  const [lastCheck, setLastCheck] = useState('')

  const checkHealth = async () => {
    const checks = await Promise.allSettled([
      timedFetch(getKavachHealth),
      timedFetch(getMARLHealth),
      timedFetch(getGateHealth),
    ])

    setServices([
      resolveStatus('Kavach++ Advisory', ':8082', checks[0]),
      resolveStatus('MARL Scheduler', ':8081', checks[1]),
      resolveStatus('Authorization Gate', ':8087', checks[2]),
    ])
    setLastCheck(new Date().toLocaleTimeString())
  }

  useEffect(() => {
    checkHealth()
    const id = setInterval(checkHealth, 10000)
    return () => clearInterval(id)
  }, [])

  const allOk = services.every(s => s.status === 'ok')

  return (
    <div className="space-y-6">
      {/* Overall Status */}
      <div className={`glass-panel p-5 border ${allOk ? 'border-emerald-500/30' : 'border-amber-500/30'}`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={`w-4 h-4 rounded-full ${allOk ? 'status-ok' : 'status-warn'}`} />
            <div>
              <p className="text-sm font-semibold text-white">
                {allOk ? 'All Systems Operational' : 'Degraded Performance'}
              </p>
              <p className="text-xs text-slate-500">Last checked: {lastCheck || 'checking...'}</p>
            </div>
          </div>
          <button
            onClick={checkHealth}
            className="px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-xs text-slate-300 hover:border-slate-500"
          >
            Check Now
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Services */}
        <div className="glass-panel p-5">
          <h3 className="text-sm font-semibold text-white mb-4">Microservices</h3>
          <div className="space-y-3">
            {services.map(svc => (
              <div key={svc.name} className="flex items-center gap-3 p-3 bg-slate-800/30 rounded-lg">
                <div className={`status-indicator ${
                  svc.status === 'ok' ? 'status-ok' : svc.status === 'degraded' ? 'status-warn' : 'status-error'
                }`} />
                <div className="flex-1">
                  <p className="text-xs font-medium text-white">{svc.name}</p>
                  <p className="text-[10px] text-slate-500">localhost{svc.url}</p>
                </div>
                {svc.latency && (
                  <span className="text-[10px] font-mono text-slate-400">{svc.latency}ms</span>
                )}
                <span className={`text-[10px] px-2 py-0.5 rounded font-semibold ${
                  svc.status === 'ok' ? 'bg-emerald-500/20 text-emerald-400' :
                  svc.status === 'degraded' ? 'bg-amber-500/20 text-amber-400' :
                  'bg-red-500/20 text-red-400'
                }`}>
                  {svc.status.toUpperCase()}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Infrastructure */}
        <div className="glass-panel p-5">
          <h3 className="text-sm font-semibold text-white mb-4">Infrastructure</h3>
          <div className="space-y-3">
            {infra.map(inf => (
              <div key={inf.name} className="flex items-center gap-3 p-3 bg-slate-800/30 rounded-lg">
                <div className={`status-indicator ${
                  inf.status === 'ok' ? 'status-ok' : 'status-warn'
                }`} />
                <div className="flex-1">
                  <p className="text-xs font-medium text-white">{inf.name}</p>
                  <p className="text-[10px] text-slate-500">{inf.detail}</p>
                </div>
                <span className="text-[10px] font-mono text-slate-500">:{inf.port}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Architecture Tier Diagram */}
      <div className="glass-panel p-5">
        <h3 className="text-sm font-semibold text-white mb-4">Architecture Tiers</h3>
        <div className="space-y-3">
          {[
            { tier: 4, label: 'Central Core', items: 'Kafka, InfluxDB, MLflow, Prometheus, Kong, Keycloak', color: 'sky' },
            { tier: 3, label: 'Zone Compute', items: 'FL Aggregator (Flower), HetGNN Delay Predictor', color: 'indigo' },
            { tier: 2, label: 'Station Edge', items: 'YOLOv8, LSTM Maintenance, Heartbeat FSM', color: 'purple' },
            { tier: 1, label: 'Micro-Edge Sensors', items: 'Vibration, GPS, Temperature, Cameras, RFID', color: 'slate' },
          ].map(t => (
            <div key={t.tier} className={`p-3 rounded-lg border border-${t.color}-500/20 bg-${t.color}-500/5`}>
              <div className="flex items-center gap-3">
                <span className={`text-xs font-bold px-2 py-0.5 rounded bg-${t.color}-500/20 text-${t.color}-400`}>
                  T{t.tier}
                </span>
                <div>
                  <p className="text-xs font-medium text-white">{t.label}</p>
                  <p className="text-[10px] text-slate-500">{t.items}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

async function timedFetch(fn: () => Promise<any>): Promise<{ data: any; latency: number }> {
  const start = Date.now()
  const data = await fn()
  return { data, latency: Date.now() - start }
}

function resolveStatus(name: string, url: string, result: PromiseSettledResult<any>): ServiceStatus {
  if (result.status === 'fulfilled') {
    return { name, url, status: 'ok', latency: result.value.latency }
  }
  return { name, url, status: 'down' }
}
