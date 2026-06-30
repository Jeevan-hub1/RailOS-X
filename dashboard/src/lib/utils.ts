import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-IN', { 
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false 
  })
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
}

// ── Risk Tier Styling ────────────────────────────────────────────────────────
// Tier 1 = CRITICAL (dual-auth required, red)
// Tier 2 = HIGH (single-auth, amber)
// Tier 3 = NORMAL (single-auth, green)

export function tierColor(tier: number): string {
  if (tier === 1) return 'tier-1'
  if (tier === 2) return 'tier-2'
  return 'tier-3'
}

export function tierBorderBg(tier: number): string {
  if (tier === 1) return 'border-red-500/30 bg-red-500/5'
  if (tier === 2) return 'border-amber-500/30 bg-amber-500/5'
  return 'border-emerald-500/30 bg-emerald-500/5'
}

export function tierBadge(tier: number): string {
  if (tier === 1) return 'bg-red-500/20 text-red-400 border-red-500/30'
  if (tier === 2) return 'bg-amber-500/20 text-amber-400 border-amber-500/30'
  return 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
}

export function tierText(tier: number): string {
  if (tier === 1) return 'text-red-400'
  if (tier === 2) return 'text-amber-400'
  return 'text-emerald-400'
}

export function tierLabel(tier: number): string {
  if (tier === 1) return 'CRITICAL'
  if (tier === 2) return 'HIGH'
  return 'NORMAL'
}

export function tierIcon(tier: number): string {
  if (tier === 1) return '\u26A0\uFE0F'   // warning
  if (tier === 2) return '\u26A1'          // lightning
  return '\u2705'                           // checkmark
}

// ── Architecture Tier Styling (Edge Compute Layers) ──────────────────────────
// T1 Micro-Edge, T2 Station Edge, T3 Zone Compute, T4 Central Core

export function archTierColor(tier: number): { border: string; bg: string; badge: string; text: string } {
  switch (tier) {
    case 1: return { border: 'border-slate-500/30', bg: 'bg-slate-500/5', badge: 'bg-slate-500/20 text-slate-400', text: 'text-slate-400' }
    case 2: return { border: 'border-purple-500/30', bg: 'bg-purple-500/5', badge: 'bg-purple-500/20 text-purple-400', text: 'text-purple-400' }
    case 3: return { border: 'border-indigo-500/30', bg: 'bg-indigo-500/5', badge: 'bg-indigo-500/20 text-indigo-400', text: 'text-indigo-400' }
    case 4: return { border: 'border-sky-500/30', bg: 'bg-sky-500/5', badge: 'bg-sky-500/20 text-sky-400', text: 'text-sky-400' }
    default: return { border: 'border-slate-700', bg: 'bg-slate-800/30', badge: 'bg-slate-700 text-slate-400', text: 'text-slate-400' }
  }
}

// ── Severity Helpers ─────────────────────────────────────────────────────────
export function severityColor(severity: string): string {
  switch (severity.toUpperCase()) {
    case 'CRITICAL': return 'text-red-400'
    case 'HIGH': return 'text-amber-400'
    case 'MEDIUM': return 'text-sky-400'
    case 'LOW': return 'text-slate-400'
    default: return 'text-slate-400'
  }
}

export function severityBadge(severity: string): string {
  switch (severity.toUpperCase()) {
    case 'CRITICAL': return 'bg-red-500/20 text-red-400'
    case 'HIGH': return 'bg-amber-500/20 text-amber-400'
    case 'MEDIUM': return 'bg-sky-500/20 text-sky-400'
    case 'LOW': return 'bg-slate-700 text-slate-400'
    default: return 'bg-slate-700 text-slate-400'
  }
}
