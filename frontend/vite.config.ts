import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// base: relative asset paths, so the built app works whether it's served
// from a domain root or a GitHub Pages project subpath (/<repo>/) — see
// useListings.ts, which already reads data via import.meta.env.BASE_URL.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: './',
})
