'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { ShieldCheck, ArrowLeft, Loader2, Lock, Mail, User, KeyRound } from 'lucide-react'
import {
  signInDemo,
  signInWithKeycloak,
  DEMO_ROLES,
  KEYCLOAK_ENABLED,
} from '@/lib/auth'

const DEMO_EMAIL = 'controller@railos.in'

type Mode = 'keycloak' | 'demo'

export default function LoginPage() {
  const router = useRouter()
  const [mode, setMode] = useState<Mode>(KEYCLOAK_ENABLED ? 'keycloak' : 'demo')
  const [name, setName] = useState('Ctrl. Sharma')
  const [identifier, setIdentifier] = useState(KEYCLOAK_ENABLED ? 'controller' : DEMO_EMAIL)
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<string>(DEMO_ROLES[0].id)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')

    if (!identifier.trim() || !password.trim()) {
      setError('Please enter both ' + (mode === 'keycloak' ? 'username' : 'email') + ' and password.')
      return
    }

    setLoading(true)
    try {
      if (mode === 'keycloak') {
        await signInWithKeycloak(identifier.trim(), password)
      } else {
        // Demo: client-side only, no backend call.
        await new Promise((r) => setTimeout(r, 400))
        signInDemo({ name: name.trim() || 'Operator', email: identifier.trim(), role })
      }
      router.push('/dashboard')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed.')
      setLoading(false)
    }
  }

  function fillDemoCreds() {
    if (mode === 'keycloak') {
      setIdentifier('controller')
      setPassword('railos-demo')
    } else {
      setName('Ctrl. Sharma')
      setIdentifier(DEMO_EMAIL)
      setPassword('railos-demo')
      setRole(DEMO_ROLES[0].id)
    }
    setError('')
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4 bg-[hsl(var(--background))] relative">
      <div className="pointer-events-none fixed inset-0 overflow-hidden">
        <div className="absolute -top-40 left-1/4 h-96 w-96 rounded-full bg-sky-600/10 blur-3xl" />
        <div className="absolute bottom-0 right-1/4 h-96 w-96 rounded-full bg-indigo-600/10 blur-3xl" />
      </div>

      <div className="relative z-10 w-full max-w-md">
        <Link
          href="/"
          className="inline-flex items-center gap-2 text-xs text-slate-400 hover:text-white transition-colors mb-6"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Back to home
        </Link>

        <div className="glass-panel p-7 lg:p-8">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-11 h-11 rounded-lg bg-gradient-to-br from-sky-500 to-blue-700 flex items-center justify-center text-white font-bold">
              RX
            </div>
            <div>
              <h1 className="text-lg font-bold text-white leading-tight">RailOS-X Console</h1>
              <p className="text-[11px] text-slate-500 uppercase tracking-wider">Operations Control Center</p>
            </div>
          </div>

          {/* Mode toggle (only when Keycloak is configured) */}
          {KEYCLOAK_ENABLED && (
            <div className="flex p-1 mb-5 rounded-lg bg-slate-900/70 border border-slate-700 text-xs">
              <button
                type="button"
                onClick={() => { setMode('keycloak'); setError('') }}
                className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-md transition-colors ${
                  mode === 'keycloak' ? 'bg-sky-600 text-white' : 'text-slate-400 hover:text-white'
                }`}
              >
                <KeyRound className="w-3.5 h-3.5" /> Keycloak SSO
              </button>
              <button
                type="button"
                onClick={() => { setMode('demo'); setError('') }}
                className={`flex-1 py-1.5 rounded-md transition-colors ${
                  mode === 'demo' ? 'bg-sky-600 text-white' : 'text-slate-400 hover:text-white'
                }`}
              >
                Demo
              </button>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {mode === 'demo' && (
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1.5">Full name</label>
                <div className="relative">
                  <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Your name"
                    className="w-full pl-9 pr-3 py-2.5 rounded-lg bg-slate-900/70 border border-slate-700 text-sm text-white placeholder:text-slate-600 focus:outline-none focus:border-sky-500/60 focus:ring-1 focus:ring-sky-500/40"
                  />
                </div>
              </div>
            )}

            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1.5">
                {mode === 'keycloak' ? 'Username' : 'Email'}
              </label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
                <input
                  type="text"
                  value={identifier}
                  onChange={(e) => setIdentifier(e.target.value)}
                  placeholder={mode === 'keycloak' ? 'controller' : 'you@railos.in'}
                  autoComplete="username"
                  className="w-full pl-9 pr-3 py-2.5 rounded-lg bg-slate-900/70 border border-slate-700 text-sm text-white placeholder:text-slate-600 focus:outline-none focus:border-sky-500/60 focus:ring-1 focus:ring-sky-500/40"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1.5">Password</label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  autoComplete="current-password"
                  className="w-full pl-9 pr-3 py-2.5 rounded-lg bg-slate-900/70 border border-slate-700 text-sm text-white placeholder:text-slate-600 focus:outline-none focus:border-sky-500/60 focus:ring-1 focus:ring-sky-500/40"
                />
              </div>
            </div>

            {mode === 'demo' && (
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1.5">Role</label>
                <select
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                  className="w-full px-3 py-2.5 rounded-lg bg-slate-900/70 border border-slate-700 text-sm text-white focus:outline-none focus:border-sky-500/60 focus:ring-1 focus:ring-sky-500/40"
                >
                  {DEMO_ROLES.map((r) => (
                    <option key={r.id} value={r.id} className="bg-slate-900">
                      {r.label}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {error && (
              <p className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold bg-sky-600 hover:bg-sky-500 disabled:opacity-60 disabled:cursor-not-allowed text-white transition-colors"
            >
              {loading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Signing in…
                </>
              ) : (
                <>
                  <ShieldCheck className="w-4 h-4" />
                  {mode === 'keycloak' ? 'Sign in with Keycloak' : 'Sign in to Console'}
                </>
              )}
            </button>
          </form>

          <div className="mt-5 pt-5 border-t border-slate-800">
            <div className="flex items-center justify-between gap-2">
              <p className="text-[11px] text-slate-500 leading-relaxed">
                {mode === 'keycloak'
                  ? 'Authenticates against Keycloak; roles come from the signed token and are enforced server-side by the Authorization Gate.'
                  : 'Demo session only — no real authentication. Roles below mirror the backend RBAC model.'}
              </p>
              <button
                onClick={fillDemoCreds}
                type="button"
                className="shrink-0 text-[11px] font-medium text-sky-400 hover:text-sky-300 underline underline-offset-2"
              >
                Use demo
              </button>
            </div>
          </div>
        </div>

        <p className="text-center text-[11px] text-slate-600 mt-5">
          {KEYCLOAK_ENABLED
            ? 'Keycloak realm: railos · demo users: controller / security / engineer / governance (pw: railos-demo)'
            : 'Set NEXT_PUBLIC_KEYCLOAK_URL to enable Keycloak SSO. Production access is governed by the server-side Authorization Gate.'}
        </p>
      </div>
    </div>
  )
}
