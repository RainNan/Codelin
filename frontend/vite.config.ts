import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const proxy = { '/api': { target: env.VITE_BACKEND_URL || 'http://127.0.0.1:8000', changeOrigin: true } }
  return { plugins: [react(), tailwindcss()], server: { port: 5173, proxy }, preview: { proxy } }
})
