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
          DEFAULT: '#ffffff',
          secondary: '#f7f6f4',
          tertiary: '#eeece8',
          dark: '#000000',
          'dark-secondary': '#0a0a0a',
          'dark-tertiary': '#171717',
        },
        border: {
          DEFAULT: '#e5e2dc',
          dark: '#262626',
        },
        accent: {
          DEFAULT: '#2f9e5c',
          hover: '#268049',
          light: '#d7f0e0',
          'dark-hover': '#4cbf7c',
        },
        // Secondary/tertiary meet WCAG AA (4.5:1) on every surface color of
        // their theme, including surface-tertiary hover/chip backgrounds.
        text: {
          primary: '#1f1e1d',
          secondary: '#5f5e5a', // 6.49 white, 6.01 secondary, 5.50 tertiary
          tertiary: '#6a6862', // 5.57 white, 5.16 secondary, 4.72 tertiary
          'dark-primary': '#f5f5f5',
          'dark-secondary': '#a3a3a3',
          'dark-tertiary': '#858585', // 5.69 black, 5.37 dark-secondary, 4.86 dark-tertiary
        },
      },
      fontFamily: {
        sans: ['Geist', 'system-ui', '-apple-system', 'sans-serif'],
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
