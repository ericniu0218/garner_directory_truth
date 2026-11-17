import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In dev, forward API calls to the Go server so the browser sees one origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': process.env.API_URL ?? 'http://localhost:8080' },
  },
})
