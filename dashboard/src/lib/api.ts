/**
 * RailOS-X API Client — connects to running backend services.
 * Attaches the Keycloak Bearer token (when signed in via SSO) so the backend
 * Authorization Gate / auth_middleware can enforce RBAC.
 */
import { getToken } from './auth'

const KAVACH_URL = process.env.NEXT_PUBLIC_KAVACH_URL || 'http://localhost:8082'
const MARL_URL = process.env.NEXT_PUBLIC_MARL_URL || 'http://localhost:8081'
const GATE_URL = process.env.NEXT_PUBLIC_GATE_URL || 'http://localhost:8087'

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/** fetch wrapper that injects the Authorization header when authenticated. */
async function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const headers = { ...(init.headers as Record<string, string> | undefined), ...authHeaders() }
  return fetch(input, { ...init, headers })
}

// ── Kavach Advisory ──────────────────────────────────────────────────────────
export interface KavachBrakingPhases {
  reactionDist_m: number
  propagationDist_m: number
  brakingDist_m: number
  totalTime_s: number
  peakDecel_ms2: number
  brakeFade: number
}

export interface KavachSafetyInvariant {
  satisfied: boolean
  clamped: boolean
  marginPct: number
}

export interface KavachEnvironment {
  humidityPct: number
  headwindKmh: number
  ambientTempC: number
}

export interface KavachAdvisory {
  alertType: string
  label: string
  advisoryStoppingDist_m: number
  certifiedStoppingDist_m: number
  speedKmh: number
  adhesionCoeff: number
  gradientRad: number
  curveRadiusM: number
  trainType: string
  brakingPhases: KavachBrakingPhases
  safetyInvariant: KavachSafetyInvariant
  environment: KavachEnvironment
  computeLatencyMs: number
  timestamp_utc: string
  alertId: string
}

export interface KavachRequestParams {
  speed_kmh: number
  lat: number
  lon: number
  vibration_rms: number
  humidity_pct?: number
  headwind_kmh?: number
  ambient_temp_c?: number
  train_type?: string
}

export async function getKavachAdvisory(
  params: KavachRequestParams
): Promise<KavachAdvisory | { status: string }> {
  const res = await apiFetch(`${KAVACH_URL}/api/v1/kavach-advisory`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  return res.json()
}

export async function getKavachHealth(): Promise<{ status: string }> {
  const res = await apiFetch(`${KAVACH_URL}/health`)
  return res.json()
}

// ── MARL Scheduler ───────────────────────────────────────────────────────────
export interface MARLAction {
  segmentId: string
  enterAt: string
  exitAt: string
  speedKmh: number
  transitMin: number
  platform?: number
}

export interface MARLAssignment {
  trainId: string
  trainClass: string
  priority: number
  actions: MARLAction[]
  delayDeltaMin: number
  originalSlot: string
  rescheduledSlot: string
}

export interface MARLMetrics {
  totalDelayMin: number
  maxSingleDelayMin: number
  affectedPassengers: number
  energyImpactPct: number
  conflictsResolved: number
  headwayViolationsFixed: number
  platformReassignments: number
  computationMs: number
}

export interface MARLConstraints {
  minHeadwaySeconds: number
  segmentsEvaluated: number
  corridorLength_km: number
}

export interface MARLProposal {
  proposalId: string
  disruptionEventId: string
  disruptionType: string
  timestamp_utc: string
  conflictFree: boolean
  assignments: MARLAssignment[]
  metrics: MARLMetrics
  constraints: MARLConstraints
  totalPassengerDelayMin: number
  riskScore: number
  riskTier: number
  modelVersion: string
}

export async function submitDisruption(
  disruptionEventId: string,
  type: string,
  affectedTrains: string[],
  affectedSegment?: string
): Promise<MARLProposal> {
  const res = await apiFetch(`${MARL_URL}/api/v1/scheduler/propose`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ disruptionEventId, type, affectedTrains, affectedSegment }),
  })
  return res.json()
}

export async function getMARLHistory(): Promise<{ proposals: MARLProposal[] }> {
  const res = await apiFetch(`${MARL_URL}/api/v1/scheduler/history`)
  return res.json()
}

export async function getMARLCorridor(): Promise<{ segments: Array<{
  segmentId: string; startKm: number; endKm: number; maxSpeedKmh: number;
  capacity: number; hasLoop: boolean; platformCount: number
}> }> {
  const res = await apiFetch(`${MARL_URL}/api/v1/scheduler/corridor`)
  return res.json()
}

export async function getMARLHealth(): Promise<{ status: string; modelVersion: string }> {
  const res = await apiFetch(`${MARL_URL}/health`)
  return res.json()
}

// ── Authorization Gate ───────────────────────────────────────────────────────
export interface QueuedAdvisory {
  advisoryId: string
  riskScore: number
  riskTier: number
  severity: string
  payload: Record<string, any>
  source: string
  createdUtc: string
  ageSeconds: number
  escalated: boolean
  escalationCount: number
  escalationTimeoutS: number
  timeToEscalationS: number
  awaitingSecondAuth: boolean
  firstAuthBy: string | null
  firstAuthAt: string | null
}

export interface GateQueue {
  advisories: QueuedAdvisory[]
}

export interface GateStats {
  totalEnqueued: number
  totalAuthorized: number
  totalRejected: number
  totalEscalated: number
  currentQueueDepth: number
  avgDecisionTimeS: number
  tierBreakdown: Record<string, number>
  authorizationRate: number
  escalationTimeouts: Record<string, number>
}

export interface GateAuditEntry {
  auditId: string
  advisoryId: string
  action: string
  controllerId: string
  controllerName: string
  controllerRole: string
  timestamp_utc: string
  riskTier: number
  riskScore: number
  decisionTimeS: number
  reason: string
  wasEscalated: boolean
}

export interface GateController {
  id: string
  name: string
  role: string
  station: string
}

export async function enqueueAdvisory(
  advisoryId: string, payload: Record<string, any>,
  probability: number, severity: string, source?: string
): Promise<{ advisoryId: string; riskScore: number; riskTier: number; escalationTimeoutS: number }> {
  const res = await apiFetch(`${GATE_URL}/api/v1/gate/enqueue`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ advisoryId, payload, probability, severity, source: source || 'simulation' }),
  })
  return res.json()
}

export async function getGateQueue(): Promise<GateQueue> {
  const res = await apiFetch(`${GATE_URL}/api/v1/gate/queue`)
  return res.json()
}

export async function authorizeAdvisory(
  advisoryId: string, controllerId: string, action: 'AUTHORIZE' | 'REJECT', reason?: string
): Promise<{ status: string; decisionTimeS?: number; authorizedBy?: string; rejectedBy?: string }> {
  const res = await apiFetch(`${GATE_URL}/api/v1/gate/authorize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ advisoryId, controllerId, action, reason: reason || '' }),
  })
  return res.json()
}

export async function getGateStats(): Promise<GateStats> {
  const res = await apiFetch(`${GATE_URL}/api/v1/gate/stats`)
  return res.json()
}

export async function getGateAudit(): Promise<{ entries: GateAuditEntry[] }> {
  const res = await apiFetch(`${GATE_URL}/api/v1/gate/audit`)
  return res.json()
}

export async function getGateControllers(): Promise<{ controllers: GateController[] }> {
  const res = await apiFetch(`${GATE_URL}/api/v1/gate/controllers`)
  return res.json()
}

export async function getGateHealth(): Promise<{ status: string; gate: string; queueDepth: number }> {
  const res = await apiFetch(`${GATE_URL}/health`)
  return res.json()
}
