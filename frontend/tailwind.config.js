/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        tier: {
          low:      '#15803d',
          medium:   '#a16207',
          high:     '#c2410c',
          critical: '#b91c1c',
        },
      },
    },
  },
  plugins: [],
}
