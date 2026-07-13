import { defineConfig, devices } from "@playwright/test";

// Serves the static dashboard (apps/dashboard) and runs the browser tests against it.
export default defineConfig({
  testDir: ".",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  reporter: "list",
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
  },
  webServer: {
    command: "python3 -m http.server 3000 --directory ..",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
