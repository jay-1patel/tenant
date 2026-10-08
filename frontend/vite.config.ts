import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

const BACKEND = process.env.BACKEND_ORIGIN || 'http://localhost:9000'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: true,
    port: 5173,
    strictPort: true,
    allowedHosts: ['prominent-faster-dropper.ngrok-free.dev'],
    // The API is proxied so the browser talks to a single origin. The backend's
    // CORS allow-list does not include :5173, so the proxy is the supported path.
    proxy: {
      '/api': { target: BACKEND, changeOrigin: true, ws: true },
      '/catalog': { target: BACKEND, changeOrigin: true },
      '/ws': { target: BACKEND, ws: true, changeOrigin: true },
    },
  },
})
