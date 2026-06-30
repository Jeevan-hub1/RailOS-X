/**
 * RailOS-X — lightweight client-side demo auth.
 *
 * NOTE: This is a front-end-only demonstration session for local dev / the
 * pilot console. It does NOT perform real authentication. The production
 * Authorization Gate enforces role-based, dual-authorization controls
 * server-side (see services/authorization_gate + services/auth_middleware).
 */

const STORAGE_KEY = 'railos_auth'

export interface DemoSession {
  name: string
  email: string
  role: string
  signedInAt: string
}

export const DEMO_ROLES = [
  { id: 'Operations_Controller', label: 'Operations Controller' },
  { id: 'Security_Officer', label: 'Security Officer' },
  { id: 'Engineering_Team', label: 'Engineering Team' },
  { id: 'Governance_Officer', label: 'Governance Officer' },
] as const

/** Human-friendly label for a canonical role id (e.g. Operations_Controller). */
export function roleLabel(role: string): string {
  const match = DEMO_ROLES.find((r) => r.id === role)
  return match ? match.label : role.replace(/_/g, ' ')
}

export function signIn(session: Omit<DemoSession, 'signedInAt'>): void {
  if (typeof window === 'undefined') return
  const payload: DemoSession = { ...session, signedInAt: new Date().toISOString() }
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(payload))
}

export function signOut(): void {
  if (typeof window === 'undefined') return
  window.localStorage.removeItem(STORAGE_KEY)
}

export function getSession(): DemoSession | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as DemoSession) : null
  } catch {
    return null
  }
}

export function isAuthenticated(): boolean {
  return getSession() !== null
}
