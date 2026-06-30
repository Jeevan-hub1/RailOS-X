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
  'Operations Controller',
  'Security Officer',
  'Maintenance Supervisor',
  'Observer (read-only)',
] as const

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
