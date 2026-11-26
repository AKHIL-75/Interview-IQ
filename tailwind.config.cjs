/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
      colors: {
        page: 'var(--ui-page)',
        surface: 'var(--ui-surface)',
        subtle: 'var(--ui-subtle)',
        heading: 'var(--ui-heading)',
        ink: 'var(--ui-ink)',
        secondary: 'var(--ui-secondary)',
        line: 'var(--ui-line)',
        primary: 'var(--ui-primary)',
        pressed: 'var(--ui-pressed)',
        selected: 'var(--ui-selected)',
        success: 'var(--ui-success)',
        'success-surface': 'var(--ui-success-bg)',
        warning: 'var(--ui-warning)',
        'warning-surface': 'var(--ui-warning-bg)',
        danger: 'var(--ui-error)',
        'danger-surface': 'var(--ui-error-bg)',
        dark: {
          50: '#f8fafc',
          100: '#e2e8f0',
          200: '#94a3b8',
          300: '#64748b',
          400: '#334155',
          500: '#1e293b',
          600: '#141a2e',
          700: '#0f1225',
          800: '#0b0e1a',
          900: '#0a0a0f',
          950: '#050508',
        },
        accent: {
          50: '#eef2ff',
          100: '#e0e7ff',
          200: '#c7d2fe',
          300: '#a5b4fc',
          400: '#818cf8',
          500: '#6366f1',
          600: '#4f46e5',
          700: '#4338ca',
          800: '#3730a3',
          900: '#312e81',
        },
        rose: {
          400: '#fb7185',
          500: '#f43f5e',
          600: '#e11d48',
        }
      },
      backgroundImage: {
        'gradient-radial': 'radial-gradient(var(--tw-gradient-stops))',
      },
      animation: {
        'fade-in': 'fadeIn 0.5s ease-out',
        'fade-in-up': 'fadeInUp 0.6s ease-out',
        'slide-in-left': 'slideInLeft 0.4s ease-out',
        'slide-in-right': 'slideInRight 0.4s ease-out',
        'pulse-slow': 'pulse 3s infinite',
        'float': 'float 6s ease-in-out infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        fadeInUp: {
          '0%': { opacity: '0', transform: 'translateY(20px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        slideInLeft: {
          '0%': { opacity: '0', transform: 'translateX(-20px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
        slideInRight: {
          '0%': { opacity: '0', transform: 'translateX(20px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-10px)' },
        },
      },
    },
  },
  plugins: [],
}
