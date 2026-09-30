import react from '@vitejs/plugin-react'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [react()],
    server: {
      // The browser only ever talks to the Vite origin; /api is forwarded to
      // FastAPI. Same-origin in development mirrors Nginx in production and
      // lets the SameSite=Strict refresh cookie work (docs/ARCHITECTURE.md D20).
      proxy: {
        '/api': {
          target: env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
      },
    },
    test: {
      environment: 'jsdom',
      setupFiles: './src/test/setup.js',
      env: { VITE_API_BASE_URL: '/api/v1' },
    },
  }
})
