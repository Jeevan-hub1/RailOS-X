import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './src/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        rail: {
          50: '#f0f9ff',
          100: '#e0f2fe',
          200: '#bae6fd',
          300: '#7dd3fc',
          400: '#38bdf8',
          500: '#0ea5e9',
          600: '#0284c7',
          700: '#0369a1',
          800: '#075985',
          900: '#0c4a6e',
          950: '#082f49',
        },
        danger: { DEFAULT: '#ef4444', dark: '#dc2626' },
        warning: { DEFAULT: '#f59e0b', dark: '#d97706' },
        success: { DEFAULT: '#10b981', dark: '#059669' },
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'train-move': 'trainMove 8s linear infinite',
      },
      keyframes: {
        trainMove: {
          '0%': { left: '0%' },
          '100%': { left: '100%' },
        },
      },
    },
  },
  plugins: [],
}
export default config
