/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        background:     '#FDFCF8',  // Rice Paper
        foreground:     '#2C2C24',  // Deep Loam
        primary: {
          DEFAULT: '#5D7052',  // Moss Green
          foreground: '#F3F4F1',  // Pale Mist
        },
        secondary: {
          DEFAULT: '#C18C5D',  // Terracotta / Clay
          foreground: '#FFFFFF',
        },
        accent: {
          DEFAULT: '#E6DCCD',  // Sand / Beige
          foreground: '#4A4A40',  // Bark
        },
        muted: {
          DEFAULT: '#F0EBE5',  // Stone
          foreground: '#78786C',  // Dried Grass
        },
        border: '#DED8CF',  // Raw Timber
        destructive: '#A85448',  // Burnt Sienna
      },
      fontFamily: {
        serif: ['Fraunces', 'Georgia', 'serif'],
        sans:  ['Nunito', 'Quicksand', 'system-ui', 'sans-serif'],
      },
      borderRadius: {
        '4xl': '2rem',
        '5xl': '2.5rem',
        'blob-1': '60% 40% 30% 70% / 60% 30% 70% 40%',
        'blob-2': '30% 70% 70% 30% / 30% 30% 70% 70%',
        'blob-3': '40% 60% 60% 40% / 50% 50% 50% 50%',
      },
      boxShadow: {
        soft:  '0 4px 20px -2px rgba(93, 112, 82, 0.15)',
        float: '0 10px 40px -10px rgba(193, 140, 93, 0.20)',
        moss:  '0 6px 24px -4px rgba(93, 112, 82, 0.25)',
        clay:  '0 6px 24px -4px rgba(193, 140, 93, 0.25)',
      },
      animation: {
        'breathe': 'breathe 8s ease-in-out infinite',
        'float':   'float 6s ease-in-out infinite',
        'fade-in': 'fadeIn 400ms ease-out',
        'lift':    'lift 200ms ease-out',
      },
      keyframes: {
        breathe: { '0%,100%': { transform: 'scale(1) rotate(0deg)' }, '50%': { transform: 'scale(1.05) rotate(2deg)' } },
        float:   { '0%,100%': { transform: 'translateY(0)' }, '50%': { transform: 'translateY(-10px)' } },
        fadeIn:  { '0%': { opacity: '0', transform: 'translateY(8px)' }, '100%': { opacity: '1', transform: 'translateY(0)' } },
        lift:    { '0%': { transform: 'translateY(0)' }, '100%': { transform: 'translateY(-4px)' } },
      },
    },
  },
  plugins: [],
}
