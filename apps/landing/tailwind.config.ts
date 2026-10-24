import type { Config } from 'tailwindcss';

// Compass design tokens — single source of truth.
// Mirrors /DESIGN.md. CI fails if tokens diverge.

const config: Config = {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    container: {
      center: true,
      padding: '1.5rem',
      screens: { '2xl': '1400px' },
    },
    extend: {
      colors: {
        // Surfaces
        bg: 'hsl(var(--bg))',
        surface: {
          DEFAULT: 'hsl(var(--surface))',
          elevated: 'hsl(var(--surface-elevated))',
          muted: 'hsl(var(--surface-muted))',
        },
        border: {
          DEFAULT: 'hsl(var(--border))',
          strong: 'hsl(var(--border-strong))',
        },
        ring: 'hsl(var(--ring))',

        // Text
        fg: {
          DEFAULT: 'hsl(var(--text-primary))',
          secondary: 'hsl(var(--text-secondary))',
          muted: 'hsl(var(--text-muted))',
        },

        // Brand accents
        accent: {
          from: 'hsl(var(--accent-from))',
          to: 'hsl(var(--accent-to))',
          DEFAULT: 'hsl(var(--accent))',
          fg: 'hsl(var(--accent-fg))',
        },
        data: 'hsl(var(--data-blue))',
        knowledge: 'hsl(var(--knowledge-green))',
        governance: 'hsl(var(--governance-amber))',
        destructive: 'hsl(var(--destructive))',
        success: 'hsl(var(--success))',
      },
      borderRadius: {
        sm: 'var(--radius-sm)',
        md: 'var(--radius-md)',
        lg: 'var(--radius-lg)',
        xl: 'var(--radius-xl)',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        serif: ['"Source Serif 4"', 'Georgia', 'serif'],
        mono: ['"JetBrains Mono"', '"SF Mono"', 'monospace'],
      },
      fontSize: {
        xs: ['11px', { lineHeight: '1.4' }],
        sm: ['13px', { lineHeight: '1.5' }],
        base: ['14px', { lineHeight: '1.5' }],
        md: ['16px', { lineHeight: '1.4' }],
        lg: ['18px', { lineHeight: '1.3' }],
        xl: ['22px', { lineHeight: '1.25' }],
        '2xl': ['28px', { lineHeight: '1.2' }],
        '3xl': ['36px', { lineHeight: '1.1' }],
      },
      backgroundImage: {
        'accent-grad':
          'linear-gradient(135deg, hsl(var(--accent-from)) 0%, hsl(var(--accent-to)) 100%)',
      },
      keyframes: {
        pulse: {
          '0%, 100%': { boxShadow: '0 0 0 0 hsl(var(--success) / 0.6)' },
          '50%': { boxShadow: '0 0 0 6px hsl(var(--success) / 0)' },
        },
      },
      animation: {
        pulse: 'pulse 2s ease-in-out infinite',
      },
    },
  },
  plugins: [require('tailwindcss-animate')],
};

export default config;
