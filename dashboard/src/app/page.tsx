import Link from 'next/link'
import {
  ShieldCheck,
  TrainFront,
  GitBranch,
  Cpu,
  Activity,
  Network,
  ArrowRight,
  Github,
  Gauge,
  Lock,
} from 'lucide-react'

const FEATURES = [
  {
    icon: ShieldCheck,
    title: 'Kavach++ Advisory',
    desc: 'Physics-based braking-curve advisories using a multi-phase deceleration model. Advisory-only, always ≥ certified distance.',
    accent: 'text-emerald-400',
    ring: 'group-hover:border-emerald-500/40',
  },
  {
    icon: TrainFront,
    title: 'MARL Scheduler',
    desc: 'Multi-agent reinforcement learning produces conflict-free rescheduling proposals during disruptions.',
    accent: 'text-sky-400',
    ring: 'group-hover:border-sky-500/40',
  },
  {
    icon: Lock,
    title: 'Authorization Gate',
    desc: 'Risk-tiered, human-in-the-loop approval with dual-authorization for critical actions and full audit trails.',
    accent: 'text-amber-400',
    ring: 'group-hover:border-amber-500/40',
  },
  {
    icon: Network,
    title: 'Edge → Zone → Core',
    desc: 'Tiered edge compute from micro-edge sensor hubs to zone orchestration and the central cognitive core.',
    accent: 'text-indigo-400',
    ring: 'group-hover:border-indigo-500/40',
  },
  {
    icon: GitBranch,
    title: 'Federated Learning',
    desc: 'Privacy-preserving model updates across stations without centralizing raw operational data.',
    accent: 'text-purple-400',
    ring: 'group-hover:border-purple-500/40',
  },
  {
    icon: Activity,
    title: 'Digital Twin',
    desc: 'Real-time corridor state, telemetry pipelines, and a live operations control center.',
    accent: 'text-rose-400',
    ring: 'group-hover:border-rose-500/40',
  },
]

const STATS = [
  { value: 'NDLS–GZB–MERT', label: 'Pilot Corridor' },
  { value: '7', label: 'Correctness Invariants' },
  { value: 'IEC 62443', label: 'Cyber-Security Scoped' },
  { value: 'Advisory-only', label: 'Safety Posture' },
]

export default function Landing() {
  return (
    <div className="min-h-screen flex flex-col bg-[hsl(var(--background))]">
      {/* Ambient background glow */}
      <div className="pointer-events-none fixed inset-0 overflow-hidden">
        <div className="absolute -top-40 -left-40 h-96 w-96 rounded-full bg-sky-600/10 blur-3xl" />
        <div className="absolute top-1/3 right-0 h-96 w-96 rounded-full bg-indigo-600/10 blur-3xl" />
        <div className="absolute bottom-0 left-1/3 h-96 w-96 rounded-full bg-emerald-600/5 blur-3xl" />
      </div>

      {/* Nav */}
      <header className="relative z-10 flex items-center justify-between px-6 lg:px-10 py-5">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-sky-500 to-blue-700 flex items-center justify-center text-white font-bold text-sm">
            RX
          </div>
          <div>
            <h1 className="text-base font-bold text-white leading-tight">RailOS-X</h1>
            <p className="text-[10px] text-slate-500 uppercase tracking-wider">Cognitive Railway OS</p>
          </div>
        </div>
        <nav className="flex items-center gap-3">
          <a
            href="https://github.com/Jeevan-hub1/RailOS-X"
            target="_blank"
            rel="noreferrer"
            className="hidden sm:flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-slate-300 hover:text-white hover:bg-slate-800/60 transition-colors"
          >
            <Github className="w-4 h-4" />
            GitHub
          </a>
          <Link
            href="/login"
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-sky-600 hover:bg-sky-500 text-white transition-colors"
          >
            Sign in
            <ArrowRight className="w-4 h-4" />
          </Link>
        </nav>
      </header>

      {/* Hero */}
      <main className="relative z-10 flex-1">
        <section className="px-6 lg:px-10 pt-12 lg:pt-20 pb-16 max-w-6xl mx-auto text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-slate-700 bg-slate-900/60 text-xs text-slate-400 mb-6">
            <span className="status-indicator status-ok" />
            Pilot corridor active · advisory-only · research & demonstration
          </div>
          <h2 className="text-4xl lg:text-6xl font-bold text-white tracking-tight leading-[1.05]">
            A cognitive operating system
            <br />
            for <span className="bg-gradient-to-r from-sky-400 to-indigo-400 bg-clip-text text-transparent">Indian Railways</span>
          </h2>
          <p className="mt-6 text-base lg:text-lg text-slate-400 max-w-2xl mx-auto">
            RailOS-X integrates real-time sensor pipelines, edge AI, federated learning, multi-agent
            scheduling, a digital twin, and IEC 62443 cyber-security — into one infrastructure-grade,
            corridor-scale platform.
          </p>
          <div className="mt-9 flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link
              href="/login"
              className="w-full sm:w-auto flex items-center justify-center gap-2 px-6 py-3 rounded-xl text-sm font-semibold bg-sky-600 hover:bg-sky-500 text-white transition-colors shadow-lg shadow-sky-600/20"
            >
              <Gauge className="w-4 h-4" />
              Open Operations Console
            </Link>
            <a
              href="https://github.com/Jeevan-hub1/RailOS-X"
              target="_blank"
              rel="noreferrer"
              className="w-full sm:w-auto flex items-center justify-center gap-2 px-6 py-3 rounded-xl text-sm font-semibold border border-slate-700 text-slate-200 hover:bg-slate-800/60 transition-colors"
            >
              <Github className="w-4 h-4" />
              View Source
            </a>
          </div>

          {/* Stats */}
          <div className="mt-14 grid grid-cols-2 lg:grid-cols-4 gap-4 max-w-4xl mx-auto">
            {STATS.map((s) => (
              <div key={s.label} className="glass-panel px-4 py-5">
                <div className="text-lg lg:text-xl font-bold text-white">{s.value}</div>
                <div className="text-[11px] text-slate-500 uppercase tracking-wider mt-1">{s.label}</div>
              </div>
            ))}
          </div>
        </section>

        {/* Features */}
        <section className="px-6 lg:px-10 pb-20 max-w-6xl mx-auto">
          <div className="text-center mb-10">
            <h3 className="text-2xl lg:text-3xl font-bold text-white">Subsystems</h3>
            <p className="text-slate-500 mt-2 text-sm">Six cooperating layers, one control plane.</p>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {FEATURES.map((f) => {
              const Icon = f.icon
              return (
                <div
                  key={f.title}
                  className={`group glass-panel p-5 border transition-colors ${f.ring}`}
                >
                  <div className="flex items-center gap-3 mb-3">
                    <div className="w-10 h-10 rounded-lg bg-slate-800/70 flex items-center justify-center">
                      <Icon className={`w-5 h-5 ${f.accent}`} />
                    </div>
                    <h4 className="text-sm font-semibold text-white">{f.title}</h4>
                  </div>
                  <p className="text-sm text-slate-400 leading-relaxed">{f.desc}</p>
                </div>
              )
            })}
          </div>
        </section>

        {/* CTA */}
        <section className="px-6 lg:px-10 pb-24 max-w-4xl mx-auto">
          <div className="glass-panel p-8 lg:p-10 text-center">
            <Cpu className="w-8 h-8 text-sky-400 mx-auto mb-4" />
            <h3 className="text-xl lg:text-2xl font-bold text-white">Step into the control center</h3>
            <p className="text-slate-400 mt-2 text-sm max-w-xl mx-auto">
              Explore the live digital twin, Kavach++ advisories, MARL proposals, and the human
              authorization gate.
            </p>
            <Link
              href="/login"
              className="mt-6 inline-flex items-center gap-2 px-6 py-3 rounded-xl text-sm font-semibold bg-sky-600 hover:bg-sky-500 text-white transition-colors"
            >
              Sign in to continue
              <ArrowRight className="w-4 h-4" />
            </Link>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="relative z-10 border-t border-slate-800 px-6 lg:px-10 py-6">
        <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-3 text-xs text-slate-500">
          <p>© {new Date().getFullYear()} RailOS-X · For research and demonstration only.</p>
          <p>All safety-critical components are advisory-only and require certification before live use.</p>
        </div>
      </footer>
    </div>
  )
}
