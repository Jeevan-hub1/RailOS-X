'use client'

import { useState, useEffect, memo } from 'react'
import { getKavachHealth, getMARLHealth, getGateHealth } from '@/lib/api'
import { archTierColor } from '@/lib/utils'

interface ServiceStatus {
  name: string
  url: string
  port: string
  status: 'ok' | 'degraded' | 'down'
  latency?: number
}

const ARCH_TIERS = [
  { tier: 4, label: 'Central Core', items: 'Kafka, InfluxDB, MLflow, Prometheus, Kong, Keycloak', desc: 'Cloud-native platform services' },
  { tier: 3, label: 'Zone Compute', items: 'Federated Learning, HetGNN Predictor, Resource Manager', desc: 'Cross-station coordination (GPU cluster)' },
  { tier: 2, label: 'Station Edge', items: 'ONNX Inference, Multi-Sensor Correlation, Aggregator', desc: 'Jetson Orin NX/AGX per station' },
  { tier: 1, label: 'Micro-Edge Sensors', items: 'Vibration 4kHz, Acoustic 48kHz, GPS, Thermal, LIDAR', desc: 'FPGA + ARM Cortex-M at trackside/bogie' },
] as const

const ArchTierCard = memo(function ArchTierCard({ tier, label, items, desc }:
  { tier: number; label: string; items: string; desc: string }) {
  const colors = archTierColor(tier)
  return (
    <div className={`p-3.5 rounded-lg border ${colors.border} ${colors.bg}`}>
      <div className="flex items-start gap-3">
        <span className={`text-[10px] font-bold px-2 py-1 rounded border ${colors.badge} ${colors.border}`}>
          T{tier}
        </span>
        <div className="flex-1">
          <p className="text-xs font-semibold text-white">{label}</p>
          <p className="text-[10px] text-slate-400 mt-0.5">{desc}</p>
          <p className="text-[10px] text-slate-500 mt-1">{items}</p>
        </div>
        <div className={`w-2 h-2 rounded-full ${tier >= 3 ? 'status-ok' : 'status-warn'}`} />
      </div>
    </div>
  )
})

export function HealthPanel() {
  const [services, setServices] = useState<ServiceStatus[]>([
    { name: 'Kavach++ Advisory', url: 'localhost:8082', port: '8082', status: 'down' },
    { name: 'MARL Scheduler', url: 'localhost:8081', port: '8081', status: 'down' },
    { name: 'Authorization Gate', url: 'localhost:8087', port: '8087', status: 'down' },
    { name: 'Micro-Edge Sensors', url: 'localhost:8090', port: '8090', status: 'down' },
    { name: 'Station Edge', url: 'localhost:8091', port: '8091', status: 'down' },
    { name: 'Zone Compute', url: 'localhost:8092', port: '8092', status: 'down' },
  ])
  const [lastCheck, setLastCheck] = useState('')

  const checkHealth = async () => {
    const checks = await Promise.allSettled([
      timedFetch(getKavachHealth),
      timedFetch(getMARLHealth),
      timedFetch(getGateHealth),
      timedFetch(() => fetch('http://localhost:8090/health').then(r => r.json())),
      timedFetch(() => fetch('http://localhost:8091/health').then(r => r.json())),
      timedFetch(() => fetch('http://localhost:8092/health').then(r => r.json())),
    ])
    setServices([
      resolveStatus('Kavach++ Advisory', 'localhost:8082', '8082', checks[0]),
      resolveStatus('MARL Scheduler', 'localhost:8081', '8081', checks[1]),
      resolveStatus('Authorization Gate', 'localhost:8087', '8087', checks[2]),
      resolveStatus('Micro-Edge Sensors', 'localhost:8090', '8090', checks[3]),
      resolveStatus('Station Edge', 'localhost:8091', '8091', checks[4]),
      resolveStatus('Zone Compute', 'localhost:8092', '8092', checks[5]),
    ])
    setLastCheck(new Date().toLocaleTimeString())
  }

  useEffect(() => {
    checkHealth()
    const id = setInterval(checkHealth, 10000)
    return () => clearInterval(id)
  }, [])

  const okCount = services.filter(s => s.status === 'ok').length
  const allOk = okCount === services.length

  const infra = [
    { name: 'Apache Kafka', port: '9094', status: 'ok' as const, detail: 'KRaft mode, 17 topics, 3 partitions' },
    { name: 'PostgreSQL 16', port: '5433', status: 'ok' as const, detail: 'Auth audit + hazard register' },
    { name: 'InfluxDB 2.7', port: '8086', status: 'ok' as const, detail: 'Sensor telemetry time-series' },
    { name: 'Redis 7', port: '6380', status: 'ok' as const, detail: 'Cache, sessions, pub/sub' },
    { name: 'MinIO (S3)', port: '9000', status: 'ok' as const, detail: 'MLflow artifacts, WORM forensic' },
  ]

  return (
    <div className="space-y-5">
      {/* Overall Status Banner */}
      <div className={`glass-panel p-4 border ${allOk ? 'border-emerald-500/30' : 'border-amber-500/30'}`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={`w-4 h-4 rounded-full ${allOk ? 'status-ok' : 'status-warn'}`} />
            <div>
              <p className="text-sm font-semibold text-white">
                {allOk ? 'All Systems Operational' : `${okCount}/${services.length} Services Online`}
              </p>
              <p className="text-[10px] text-slate-500">Last checked: {lastCheck || 'checking...'}</p>
            </div>
          </div>
          <button onClick={checkHealth}
            className="px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-xs text-slate-300 hover:border-slate-500">
            Check Now
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Microservices */}
        <div className="glass-panel p-5">
          <h3 className="text-sm font-semibold text-white mb-3">Microservices ({okCount}/{services.length})</h3>
          <div className="space-y-2">
            {services.map(svc => (
              <div key={svc.name} className="flex items-center gap-3 p-2.5 bg-slate-800/30 rounded-lg">
                <div className={`status-indicator ${
                  svc.status === 'ok' ? 'status-ok' : svc.status === 'degraded' ? 'status-warn' : 'status-error'
                }`} />
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium text-white truncate">{svc.name}</p>
                  <p className="text-[9px] text-slate-500 font-mono">{svc.url}</p>
                </div>
                {svc.latency != null && (
                  <span className={`text-[10px] font-mono ${svc.latency < 50 ? 'text-emerald-400' : svc.latency < 200 ? 'text-amber-400' : 'text-red-400'}`}>
                    {svc.latency}ms
                  </span>
                )}
                <span className={`text-[9px] px-1.5 py-0.5 rounded font-semibold ${
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
          <h3 className="text-sm font-semibold text-white mb-3">Infrastructure</h3>
          <div className="space-y-2">
            {infra.map(inf => (
              <div key={inf.name} className="flex items-center gap-3 p-2.5 bg-slate-800/30 rounded-lg">
                <div className="status-indicator status-ok" />
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium text-white">{inf.name}</p>
                  <p className="text-[9px] text-slate-500">{inf.detail}</p>
                </div>
                <span className="text-[9px] font-mono text-slate-500">:{inf.port}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Architecture Tiers */}
      <div className="glass-panel p-5">
        <h3 className="text-sm font-semibold text-white mb-1">Edge Computing Architecture</h3>
        <p className="text-[10px] text-slate-500 mb-4">4-tier hierarchy: Sensor &rarr; Station &rarr; Zone &rarr; Core</p>
        <div className="space-y-2.5">
          {ARCH_TIERS.map(t => <ArchTierCard key={t.tier} {...t} />)}
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

function resolveStatus(name: string, url: string, port: string, result: PromiseSettledResult<any>): ServiceStatus {
  if (result.status === 'fulfilled') {
    return { name, url, port, status: 'ok', latency: result.value.latency }
  }
  return { name, url, port, status: 'down' }
}
