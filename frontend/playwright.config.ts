import { defineConfig } from '@playwright/test'

// Keep local test traffic outside any system HTTP proxy.
process.env.NO_PROXY = [process.env.NO_PROXY, '127.0.0.1', 'localhost'].filter(Boolean).join(',')
process.env.no_proxy = process.env.NO_PROXY
const baseURL = process.env.CODELIN_FRONTEND || 'http://127.0.0.1:5173'

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  workers: 2,
  timeout: 30000,
  use: { baseURL, trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  webServer: { command: `npm run dev -- --strictPort --port ${new URL(baseURL).port}`, url: baseURL, reuseExistingServer: !process.env.CI },
})
