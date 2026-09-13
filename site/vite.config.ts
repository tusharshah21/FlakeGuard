import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  // Relative base so the built bundle works from any path, including a static host subdirectory.
  base: './',
  plugins: [react(), tailwindcss()],
})
