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
          dark: '#262624',
          'dark-secondary': '#1f1e1d',
          'dark-tertiary': '#30302e',
        },
        border: {
          DEFAULT: '#e5e2dc',
          dark: '#3a3936',
        },
        accent: {
          DEFAULT: '#2f9e5c',
          hover: '#268049',
          light: '#d7f0e0',
          'dark-hover': '#4cbf7c',
        },
        text: {
          primary: '#1f1e1d',
          secondary: '#6b6a66',
          tertiary: '#9a988f',
          'dark-primary': '#f2f1ed',
          'dark-secondary': '#b5b3ac',
          'dark-tertiary': '#787670',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      animation: {
        'fade-in': 'fadeIn 0.15s ease-out',
        'slide-up': 'slideUp 0.2s ease-out',
        'slide-in-right': 'slideInRight 0.2s ease-out',
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
