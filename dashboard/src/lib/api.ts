/**
 * RailOS-X API Client — connects to running backend services
 */

const KAVACH_URL = process.env.NEXT_PUBLIC_KAVACH_URL || 'http://localhost:8082'
const MARL_URL = process.env.NEXT_PUBLIC_MARL_URL || 'http://localhost:8081'
const GATE_URL = process.env.NEXT_PUBLIC_GATE_URL || 'http://localhost:8087'

// ── Kavach Advisory ──────────────────────────────────────────────────────────
export interface KavachAdvisory {
  alertType: string
  label: string
  advisoryStoppingDist_m: number
  certifiedStoppingDist_m: number
  speedKmh: number
  adhesionCoeff: number
  gradientRad: number
  timestamp_utc: string
  alertId: string
}

export async function getKavachAdvisory(
  speed_kmh: number, lat: number, lon: number, vibration_rms: number
): Promise<KavachAdvisory | { status: string }> {
  const res = await fetch(`${KAVACH_URL}/api/v1/kavach-advisory`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ speed_kmh, lat, lon, vibration_rms }),
  })
  return res.json()
}

export async function getKavachHealth(): Promise<{ status: string }> {
  const res = await fetch(`${KAVACH_URL}/health`)
  return res.json()
}

// ── MARL Scheduler ───────────────────────────────────────────────────────────
export interface MARLProposal {
  proposalId: string
  disruptionEventId: string
  timestamp_utc: string
  conflictFree: boolean
  assignments: Array<{
    trainId: string
    actions: Array<{ segmentId: string; enterAt: string; exitAt: string }>
    delayDeltaMin: number
  }>
  totalPassengerDelayMin: number
  riskScore: number
  riskTier: number
  modelVersion: string
}

export async function submitDisruption(
  disruptionEventId: string,
  type: string,
  affectedTrains: string[]
): Promise<MARLProposal> {
  const res = await fetch(`${MARL_URL}/api/v1/scheduler/propose`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ disruptionEventId, type, affectedTrains }),
  })
  return res.json()
}

export async function getMARLHealth(): Promise<{ status: string }> {
  const res = await fetch(`${MARL_URL}/health`)
  return res.json()
}

// ── Authorization Gate ───────────────────────────────────────────────────────
export interface QueuedAdvisory {
  advisoryId: string
  riskScore: number
  riskTier: number
  payload: Record<string, any>
}

export interface GateQueue {
  advisories: QueuedAdvisory[]
}

export async function enqueueAdvisory(
  advisoryId: string, payload: Record<string, any>,
  probability: number, severity: string
): Promise<{ advisoryId: string; riskScore: number; riskTier: number }> {
  const res = await fetch(`${GATE_URL}/api/v1/gate/enqueue`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ advisoryId, payload, probability, severity }),
  })
  return res.json()
}

export async function getGateQueue(): Promise<GateQueue> {
  const res = await fetch(`${GATE_URL}/api/v1/gate/queue`)
  return res.json()
}

export async function authorizeAdvisory(
  advisoryId: string, controllerId: string, action: 'AUTHORIZE' | 'REJECT'
): Promise<{ status: string }> {
  const res = await fetch(`${GATE_URL}/api/v1/gate/authorize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ advisoryId, controllerId, action }),
  })
  return res.json()
}

export async function getGateHealth(): Promise<{ status: string; gate: string }> {
  const res = await fetch(`${GATE_URL}/health`)
  return res.json()
}
