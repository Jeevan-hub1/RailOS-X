/**
 * RailOS-X — dashboard authentication.
 *
 * Two modes:
 *   1. Keycloak SSO (real): when NEXT_PUBLIC_KEYCLOAK_URL is configured, the
 *      login form authenticates against Keycloak via the OIDC direct-access
 *      (password) grant, receives a signed RS256 JWT, and stores it. The JWT's
 *      `realm_access.roles` are the real backend RBAC roles, and the token is
 *      sent as a Bearer credential on API calls (see lib/api.ts). Backend
 *      services validate it through services/auth_middleware (JWKS).
 *   2. Demo (fallback): a purely client-side session for local exploration when
 *      no IdP is configured. No real authentication.
 *
 * NOTE: the direct-access grant keeps the existing username/password form simple
 * for a dev/internal console. A production deployment may prefer the redirect
 * (authorization-code + PKCE) flow.
 */

const STORAGE_KEY = 'railos_auth'

export const KEYCLOAK_URL = process.env.NEXT_PUBLIC_KEYCLOAK_URL || ''
export const KEYCLOAK_REALM = process.env.NEXT_PUBLIC_KEYCLOAK_REALM || 'railos'
export const KEYCLOAK_CLIENT_ID = process.env.NEXT_PUBLIC_KEYCLOAK_CLIENT_ID || 'railos-dashboard'
export const KEYCLOAK_ENABLED = KEYCLOAK_URL.length > 0

export interface Session {
  name: string
  email: string
  role: string
  roles: string[]
  mode: 'demo' | 'keycloak'
  token?: string
  expiresAt?: number // epoch ms
  signedInAt: string
}

// Canonical backend roles (services/auth_middleware/role_permissions.py).
export const DEMO_ROLES = [
  { id: 'Operations_Controller', label: 'Operations Controller' },
  { id: 'Security_Officer', label: 'Security Officer' },
  { id: 'Engineering_Team', label: 'Engineering Team' },
  { id: 'Governance_Officer', label: 'Governance Officer' },
] as const

/** Human-friendly label for a canonical role id (e.g. Operations_Controller). */
export function roleLabel(role: string): string {
  const match = DEMO_ROLES.find((r) => r.id === role)
  return match ? match.label : (role || '').replace(/_/g, ' ')
}

function decodeJwt(token: string): Record<string, any> {
  const part = token.split('.')[1]
  const padded = part.replace(/-/g, '+').replace(/_/g, '/')
  const json = decodeURIComponent(
    atob(padded)
      .split('')
      .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
      .join('')
  )
  return JSON.parse(json)
}

function persist(session: Session): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
}

/** Demo (client-only) sign in. */
export function signInDemo(input: { name: string; email: string; role: string }): void {
  persist({
    name: input.name,
    email: input.email,
    role: input.role,
    roles: [input.role],
    mode: 'demo',
    signedInAt: new Date().toISOString(),
  })
}

/**
 * Real Keycloak sign in via the OIDC password (direct access) grant.
 * Throws an Error with a readable message on failure.
 */
export async function signInWithKeycloak(username: string, password: string): Promise<Session> {
  if (!KEYCLOAK_ENABLED) {
    throw new Error('Keycloak is not configured (set NEXT_PUBLIC_KEYCLOAK_URL).')
  }
  const url = `${KEYCLOAK_URL.replace(/\/$/, '')}/realms/${KEYCLOAK_REALM}/protocol/openid-connect/token`
  const body = new URLSearchParams({
    client_id: KEYCLOAK_CLIENT_ID,
    grant_type: 'password',
    username,
    password,
    scope: 'openid',
  })

  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  })

  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const err = await res.json()
      detail = err.error_description || err.error || detail
    } catch {
      /* ignore */
    }
    throw new Error(`Sign-in failed: ${detail}`)
  }

  const data = await res.json()
  const claims = decodeJwt(data.access_token)
  const roles: string[] = claims?.realm_access?.roles ?? []
  // Prefer a known RBAC role for display if present.
  const primary = DEMO_ROLES.map((r) => r.id).find((r) => roles.includes(r)) || roles[0] || 'user'

  const session: Session = {
    name: claims.name || claims.preferred_username || username,
    email: claims.email || '',
    role: primary,
    roles,
    mode: 'keycloak',
    token: data.access_token,
    expiresAt: Date.now() + (data.expires_in ?? 300) * 1000,
    signedInAt: new Date().toISOString(),
  }
  persist(session)
  return session
}

export function signOut(): void {
  if (typeof window === 'undefined') return
  window.localStorage.removeItem(STORAGE_KEY)
}

export function getSession(): Session | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const s = JSON.parse(raw) as Session
    // Expire Keycloak sessions once the access token is past its lifetime.
    if (s.mode === 'keycloak' && s.expiresAt && Date.now() >= s.expiresAt) {
      window.localStorage.removeItem(STORAGE_KEY)
      return null
    }
    return s
  } catch {
    return null
  }
}

/** Bearer token for API calls, when signed in via Keycloak. */
export function getToken(): string | null {
  const s = getSession()
  return s?.token ?? null
}

export function isAuthenticated(): boolean {
  return getSession() !== null
}
