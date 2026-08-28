/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        page: '#0A0A0A',
        surface: '#111111',
        elevated: '#161616',
        ink: '#F5F5F5',
        muted: '#888888',
        label: '#666666',
        accent: '#22C55E',
        'accent-hover': '#16A34A',
        danger: '#EF4444',
        warn: '#F59E0B',
        info: '#3B82F6',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        display: ['"Playfair Display"', 'Georgia', 'serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      maxWidth: {
        shell: '1200px',
      },
      borderRadius: {
        card: '12px',
        pill: '8px',
      },
      keyframes: {
        pulseSoft: {
          '0%, 100%': { opacity: '0.6' },
          '50%': { opacity: '1' },
        },
        pulseGlow: {
          '0%, 100%': { opacity: '0.4', boxShadow: '0 0 0 0 rgba(59,130,246,0.35)' },
          '50%': { opacity: '0.8', boxShadow: '0 0 0 6px rgba(59,130,246,0)' },
        },
        fadeIn: {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        spin: {
          to: { transform: 'rotate(360deg)' },
        },
      },
      animation: {
        pulseSoft: 'pulseSoft 2s ease-in-out infinite',
        pulseGlow: 'pulseGlow 2s ease-in-out infinite',
        fadeIn: 'fadeIn 0.3s ease forwards',
        spin: 'spin 0.8s linear infinite',
      },
    },
  },
  plugins: [],
}
