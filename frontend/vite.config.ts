import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const API = process.env.HIVEOPS_API ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, proxy: { '/api': API } },
  build: { chunkSizeWarningLimit: 1200 },
  test: { environment: 'node' },
})
