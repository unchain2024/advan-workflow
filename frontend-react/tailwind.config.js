/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: '#FF4B4B',
        primaryHover: '#E63946',
        success: '#4CAF50',
        info: '#1976D2',
        warning: '#FF9800',
        error: '#F44336',
      },
    },
  },
  plugins: [],
}
