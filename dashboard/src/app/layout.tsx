import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'RailOS-X | Operations Control Center',
  description: 'Cognitive Railway Operating System — Real-time Corridor Intelligence',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  )
}
