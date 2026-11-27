/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        surface: {
          // Landing page palette: white cards on an off-white page.
          DEFAULT: '#ffffff',
          secondary: '#f2f1ef',
          tertiary: '#e7e5e1',
          dark: '#000000',
          'dark-secondary': '#0a0a0a',
          'dark-tertiary': '#171717',
        },
        border: {
          DEFAULT: '#e2dfd9',
          dark: '#262626',
        },
        // The user's accent color. The variables are set from Settings (see
        // src/lib/accent.ts); the defaults in globals.css are the original orange.
        accent: {
          DEFAULT: 'rgb(var(--accent-rgb) / <alpha-value>)',
          hover: 'rgb(var(--accent-hover-rgb) / <alpha-value>)',
          light: 'rgb(var(--accent-light-rgb) / <alpha-value>)',
          'dark-hover': 'rgb(var(--accent-dark-hover-rgb) / <alpha-value>)',
        },
        // Secondary/tertiary meet WCAG AA (4.5:1) on every surface color of
        // their theme, including surface-tertiary hover/chip backgrounds.
        text: {
          primary: '#141414',
          secondary: '#56554f', // ~7.4 white, ~6.6 secondary, ~5.9 tertiary
          tertiary: '#615f5a', // ~6.4 white, ~5.7 secondary, ~5.1 tertiary
          'dark-primary': '#f5f5f5',
          'dark-secondary': '#a3a3a3',
          'dark-tertiary': '#858585', // 5.69 black, 5.37 dark-secondary, 4.86 dark-tertiary
        },
      },
      fontFamily: {
        sans: ['Geist', 'system-ui', '-apple-system', 'sans-serif'],
        display: ['"Inter Tight"', 'Geist', 'system-ui', 'sans-serif'],
        mono: ['Geist Mono', 'ui-monospace', 'monospace'],
      },
      animation: {
        'fade-in': 'fadeIn 180ms cubic-bezier(0.22, 1, 0.36, 1)',
        'slide-up': 'slideUp 300ms cubic-bezier(0.22, 1, 0.36, 1)',
        'slide-in-right': 'slideInRight 300ms cubic-bezier(0.22, 1, 0.36, 1)',
        'pulse-dot': 'pulseDot 1.4s infinite ease-in-out',
        'shimmer': 'shimmer 2s infinite linear',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        slideInRight: {
          '0%': { opacity: '0', transform: 'translateX(6px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
        pulseDot: {
          '0%, 80%, 100%': { transform: 'scale(0)' },
          '40%': { transform: 'scale(1)' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
      },
    },
  },
  plugins: [],
}
