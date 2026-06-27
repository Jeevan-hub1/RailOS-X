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

export function tierColor(tier: number): string {
  if (tier === 1) return 'tier-1'
  if (tier === 2) return 'tier-2'
  return 'tier-3'
}

export function tierLabel(tier: number): string {
  if (tier === 1) return 'CRITICAL'
  if (tier === 2) return 'HIGH'
  return 'NORMAL'
}
