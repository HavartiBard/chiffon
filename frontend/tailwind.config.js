/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        'chiffon-primary': '#6366f1',
        'chiffon-secondary': '#8b5cf6',
      },
    },
  },
  plugins: [],
}
