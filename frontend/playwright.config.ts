import { defineConfig } from "@playwright/test";

/**
 * End-to-end smoke tests against a RUNNING stack (backend on :8001 seeded, frontend on :3000).
 * Locally uses the installed Edge (no browser download). In CI set PW_CHANNEL=chromium after
 * `npx playwright install chromium`.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    channel: process.env.PW_CHANNEL ?? "msedge",
    headless: true,
    screenshot: "only-on-failure",
  },
});
