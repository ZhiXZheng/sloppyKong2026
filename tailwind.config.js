/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        tactical: {
          bg: '#070b14',
          panel: '#0d1527',
          panelHover: '#131e36',
          panelBorder: '#1c2b48',
          subtle: '#223558',
          textMuted: '#64748b',
          textMain: '#cbd5e1',
          textBright: '#f8fafc',
          blue: '#0284c7',
          cyan: '#06b6d4',
          alpha: '#38bdf8', // Team Alpha cyan/blue
          bravo: '#22c55e', // Team Bravo green
          drone: '#a855f7', // Drone purple
          shelter: '#f59e0b', // Shelter amber
          civilian: '#eab308', // Civilian yellow/gold
          danger: '#ef4444', // Danger/Water warning red
          flood: '#1e3a8a', // Deep flood
          shallow: '#1e40af', // Submerged
        }
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
      gridTemplateColumns: {
        '20': 'repeat(20, minmax(0, 1fr))',
      },
      gridTemplateRows: {
        '20': 'repeat(20, minmax(0, 1fr))',
      }
    },
  },
  plugins: [],
}
