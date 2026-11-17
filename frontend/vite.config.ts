import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The site only talks to the twin API (backend/api/app.py). In dev, /api is proxied to it.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  build: { chunkSizeWarningLimit: 6000 },
})
